import os
from dotenv import load_dotenv
import requests
from datetime import datetime
import pytz
from bs4 import BeautifulSoup

# Load environment variables from .env file
load_dotenv()


def main():
    # GET HTML
    html_content, URL = getHTML()
    
    # SAVE HTML TO FILE
    soup = BeautifulSoup(html_content, 'html.parser')

    # SAVE HTML TO FILE FOR TESTING PURPOSES
    # with open('my_html.html', mode='w', encoding='utf-8') as f:
    #     f.write(f"{soup}")

    # SCRAPE JOB DETAILS
    job_details = soup.css.select_one('.details')

    job_url = URL
    job_title = job_details.css.select_one('.topcard__title').get_text(strip=True)
    job_company = job_details.css.select_one('.topcard__org-name-link').get_text(strip=True)
    job_location = job_details.css.select_one('.topcard__flavor.topcard__flavor--bullet').get_text(strip=True)
    job_salary = job_details.css.select_one('.salary')
    if job_salary is None:
        job_salary = "No salary info provided"
    else:
        job_salary = job_salary.get_text(strip=True)

    # SEND INFO TO JOB APPLICATIONS GOOGLE SHEET
    sendToSheets(job_url, job_title, job_company, job_location, job_salary)


def getHTML():
    # Get the job posting URL from the user
    URL = input("Please enter job posting URL from LinkedIn.\n(i.e. https://www.linkedin.com/jobs/view/4296307551):\n\n")
    print("\nGetting html...\n")

    response = requests.get(URL)
    if response.status_code == 200:
        html_content = response.text

        # send the html but also the URL so you can add that to google sheets later
        return html_content, URL
    else:
        print(f"Failed to retrieve content. Status code: {response.status_code}")


def sendToSheets(job_url, job_title, job_company, job_location, job_salary):
    print('Sending info to your google sheet...\n') # via Sheety API (see https://sheety.co/)

    sheety_auth_token = os.getenv('SHEETY_AUTH_TOKEN')
    # sheety_get_endpoint = os.getenv('SHEETY_GET_ENDPOINT')
    sheety_post_endpoint = os.getenv('SHEETY_POST_ENDPOINT')
    now = datetime.now(pytz.timezone('America/Phoenix')).strftime("%m/%d/%y")

    sheety_params = {
        "jobsAppliedForIn2025": {
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

    sheety_response = requests.post(
        sheety_post_endpoint, 
        json=sheety_params, 
        headers=sheety_headers
    )

    if sheety_response.status_code == 200 or sheety_response.status_code == 201:
        print("Info sent successfully!\n")


if __name__ == "__main__":
    main()