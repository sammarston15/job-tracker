# job-tracker

This app takes user input via terminal to automate adding job posting details (company name, job title, etc) to a Google sheet for personal job search related tracking.

## Supported job URLs

- LinkedIn: `https://www.linkedin.com/jobs/view/<job-id>`
- Simplify Jobs: `https://simplify.jobs/p/<uuid>/<job-title>`

The app fetches the job page, extracts title/company/location/salary (when available), and sends the result to your Sheety API endpoint for your Google Sheet.

## Notes

- Simplify tracking query params like `utm_source`, `utm_medium`, and `utm_campaign` are removed before storing the URL.
- If location or salary are not present on the page, fallback values are used.