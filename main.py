import os
import time
import logging
import json
import re
from dotenv import load_dotenv
import requests
from datetime import datetime
import pytz
from bs4 import BeautifulSoup
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()


def main():
    url = input(
        "Please enter job posting URL (LinkedIn or Simplify Jobs).\n"
        "Examples:\n"
        "- https://www.linkedin.com/jobs/view/4296307551\n"
        "- https://simplify.jobs/p/<uuid>/<job-title>\n\n"
    ).strip()

    if not url:
        print("No URL provided. Exiting.\n")
        return

    print("\nGetting html...\n")

    try:
        source = detect_job_source(url)
        html_content = get_html(url)
        soup = BeautifulSoup(html_content, "html.parser")

        if source == "linkedin":
            job_data = parse_linkedin_job(soup, url)
        else:
            job_data = parse_simplify_job(soup, url)

        sendToSheets(
            job_data["job_url"],
            job_data["job_title"],
            job_data["job_company"],
            job_data["job_location"],
            job_data["job_salary"],
        )
    except ValueError as error:
        print(f"Could not process this URL: {error}\n")
    except requests.RequestException as error:
        print(f"Network error while retrieving job posting: {error}\n")
    except Exception as error:
        logger.exception("Unexpected failure while processing job URL")
        print(f"Unexpected error: {error}\n")


def detect_job_source(url):
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()

    if "linkedin.com" in host and "/jobs/view" in path:
        return "linkedin"
    if "simplify.jobs" in host and path.startswith("/p/"):
        return "simplify"
    raise ValueError("Only LinkedIn job URLs and Simplify Jobs URLs are supported")


def get_html(url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        )
    }

    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text


def parse_linkedin_job(soup, original_url):
    details = soup.select_one(".details")
    if details is None:
        raise ValueError("Could not locate LinkedIn job details section")

    job_title = text_by_selectors(details, [".topcard__title", "h1"])
    job_company = text_by_selectors(
        details,
        [
            ".topcard__org-name-link",
            ".topcard__flavor-row .topcard__flavor:first-child",
            ".topcard__flavor:first-child",
        ],
    )
    job_location = text_by_selectors(
        details,
        [
            ".topcard__flavor.topcard__flavor--bullet",
            ".topcard__flavor--bullet",
            ".topcard__flavor-row .topcard__flavor--bullet",
        ],
    )
    job_salary = text_by_selectors(details, [".salary", ".compensation__salary"])

    return normalize_job_data(
        job_url=canonicalize_url(original_url),
        job_title=job_title,
        job_company=job_company,
        job_location=job_location,
        job_salary=job_salary,
    )


def parse_simplify_job(soup, original_url):
    canonical_url = canonicalize_url(original_url)
    path_segments = [segment for segment in urlparse(canonical_url).path.split("/") if segment]

    title_from_path = None
    if len(path_segments) >= 3:
        title_from_path = path_segments[2].replace("-", " ").strip()

    meta_title = get_meta_content(soup, "property", "og:title") or get_meta_content(
        soup, "name", "twitter:title"
    )
    title_from_meta = split_title_and_company(meta_title)[0] if meta_title else None

    job_title = first_non_empty(
        [
            text_by_selectors(soup, ["h1"]),
            title_from_meta,
            title_from_path,
        ]
    )

    company_from_meta = split_title_and_company(meta_title)[1] if meta_title else None
    company_from_json_ld = extract_jobposting_field(soup, ["hiringOrganization", "name"])
    job_company = first_non_empty(
        [
            text_by_selectors(soup, ["[data-testid='company-name']", "[class*='company'] a", "[class*='company'] span"]),
            company_from_json_ld,
            company_from_meta,
        ]
    )

    location_from_json_ld = extract_location_from_json_ld(soup)
    job_location = first_non_empty(
        [
            text_by_selectors(soup, ["[data-testid='location']", "[class*='location']"]),
            location_from_json_ld,
        ]
    )

    salary_from_json_ld = extract_salary_from_json_ld(soup)
    job_salary = first_non_empty(
        [
            text_by_selectors(soup, ["[data-testid='salary']", "[class*='salary']", "[class*='compensation']"]),
            salary_from_json_ld,
        ]
    )

    return normalize_job_data(
        job_url=canonical_url,
        job_title=job_title,
        job_company=job_company,
        job_location=job_location,
        job_salary=job_salary,
    )


def normalize_job_data(job_url, job_title, job_company, job_location, job_salary):
    return {
        "job_url": job_url,
        "job_title": clean_whitespace(job_title) or "Unknown title",
        "job_company": clean_whitespace(job_company) or "Unknown company",
        "job_location": clean_whitespace(job_location) or "Unknown location",
        "job_salary": clean_whitespace(job_salary) or "No salary info provided",
    }


def text_by_selectors(soup, selectors):
    for selector in selectors:
        tag = soup.select_one(selector)
        if tag:
            value = tag.get_text(" ", strip=True)
            if value:
                return value
    return None


def clean_whitespace(value):
    if value is None:
        return None
    return re.sub(r"\s+", " ", str(value)).strip()


def first_non_empty(values):
    for value in values:
        cleaned = clean_whitespace(value)
        if cleaned:
            return cleaned
    return None


def get_meta_content(soup, attr_name, attr_value):
    tag = soup.find("meta", attrs={attr_name: attr_value})
    if tag:
        content = tag.get("content")
        if content:
            return content.strip()
    return None


def split_title_and_company(meta_title):
    if not meta_title:
        return None, None
    parts = re.split(r"\s+at\s+", meta_title, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) == 2:
        return clean_whitespace(parts[0]), clean_whitespace(parts[1].split("|")[0])
    return clean_whitespace(meta_title.split("|")[0]), None


def extract_jobposting_field(soup, field_path):
    for payload in iterate_jobposting_json_ld(soup):
        current = payload
        missing = False
        for key in field_path:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                missing = True
                break
        if not missing and current:
            return current
    return None


def extract_location_from_json_ld(soup):
    for payload in iterate_jobposting_json_ld(soup):
        locations = payload.get("jobLocation")
        if not locations:
            continue
        if isinstance(locations, dict):
            locations = [locations]
        pretty_locations = []
        for location in locations:
            address = location.get("address") if isinstance(location, dict) else None
            if not isinstance(address, dict):
                continue
            pieces = [
                address.get("addressLocality"),
                address.get("addressRegion"),
                address.get("addressCountry"),
            ]
            formatted = ", ".join([piece for piece in pieces if piece])
            if formatted:
                pretty_locations.append(formatted)
        if pretty_locations:
            return "; ".join(pretty_locations)
    return None


def extract_salary_from_json_ld(soup):
    for payload in iterate_jobposting_json_ld(soup):
        base_salary = payload.get("baseSalary")
        if not isinstance(base_salary, dict):
            continue
        currency = base_salary.get("currency")
        value_block = base_salary.get("value")
        if not isinstance(value_block, dict):
            continue

        min_value = value_block.get("minValue")
        max_value = value_block.get("maxValue")
        unit = value_block.get("unitText")

        if min_value is None and max_value is None:
            continue

        if min_value is not None and max_value is not None:
            salary = f"{min_value} - {max_value}"
        else:
            salary = str(min_value if min_value is not None else max_value)

        if currency:
            salary = f"{currency} {salary}"
        if unit:
            salary = f"{salary} per {unit}"
        return salary
    return None


def iterate_jobposting_json_ld(soup):
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    for script in scripts:
        raw = script.string or script.get_text(strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        for payload in flatten_json_ld_payloads(data):
            payload_type = payload.get("@type") if isinstance(payload, dict) else None
            if payload_type == "JobPosting" or (
                isinstance(payload_type, list) and "JobPosting" in payload_type
            ):
                yield payload


def flatten_json_ld_payloads(data):
    if isinstance(data, list):
        for item in data:
            yield from flatten_json_ld_payloads(item)
    elif isinstance(data, dict):
        if "@graph" in data and isinstance(data["@graph"], list):
            for item in data["@graph"]:
                yield from flatten_json_ld_payloads(item)
        else:
            yield data


def canonicalize_url(url):
    parsed = urlparse(url)
    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(filtered_query),
            "",
        )
    )


def sendToSheets(job_url, job_title, job_company, job_location, job_salary):
    print('Sending info to your google sheet...\n') # via Sheety API (see https://sheety.co/)

    sheety_auth_token = os.getenv('SHEETY_AUTH_TOKEN')
    # sheety_get_endpoint = os.getenv('SHEETY_GET_ENDPOINT')
    sheety_post_endpoint = os.getenv('SHEETY_POST_ENDPOINT')
    now = datetime.now(pytz.timezone('America/Phoenix')).strftime("%m/%d/%y")
    sheety_sheet_name = os.getenv('SHEETY_SHEET_NAME')

    sheety_params = {
        f"{sheety_sheet_name}": {
            "company": job_company,
            "jobTitle": job_title,
            "dateApplied": now,
            "status": "application received",
            "dateUpdated": now,
            "location": job_location,
            "resources (jobDescription/applicationLink)": job_url,
            "originalComments": job_salary
        }
    }

    sheety_headers = {
        "Authorization": f"Basic {sheety_auth_token}",
        "Content-Type": "application/json"
    }

    max_attempts = 2  # initial request + one retry
    for attempt in range(max_attempts):
        try:
            sheety_response = requests.post(
                sheety_post_endpoint,
                json=sheety_params,
                headers=sheety_headers,
                timeout=30,
            )
            if sheety_response.status_code in (200, 201):
                print("Info sent successfully!\n")
                return
            # Request succeeded but API returned an error status
            logger.warning(
                "Sheety request failed (attempt %d/%d): status=%s, url=%s, response=%s",
                attempt + 1,
                max_attempts,
                sheety_response.status_code,
                sheety_post_endpoint,
                sheety_response.text[:500] if sheety_response.text else "(empty)",
            )
        except requests.RequestException as e:
            logger.warning(
                "Sheety request failed (attempt %d/%d): %s",
                attempt + 1,
                max_attempts,
                e,
                exc_info=True,
            )
        if attempt == 0:
            print("Retrying in 5 seconds...\n")
            time.sleep(5)
    print("Failed to send info to Google Sheet after 2 attempts.\n")


if __name__ == "__main__":
    main()