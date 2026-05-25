import io
import re
from typing import List, Optional

from fastapi import FastAPI, File, Form, UploadFile, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from resume import (
    USER_PROFILE,
    calculate_ats,
    analyze_job_ai,
    generate_cover_letter,
    generate_recruiter_message,
    generate_matching_resume,
    detect_visa,
    scrape_linkedin_jobs,
    auto_easy_apply,
)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape(["html", "xml"]),
)

def render_template(template_name: str, context: dict) -> HTMLResponse:
    return HTMLResponse(templates.get_template(template_name).render(**context))

SKILL_CANDIDATES = [
    "snowflake",
    "sql",
    "etl",
    "elt",
    "python",
    "iics",
    "aws",
    "azure",
    "dbt",
    "airflow",
    "data warehousing",
    "cloud data engineering",
    "analytics",
    "machine learning",
    "bigquery",
    "spark",
    "terraform",
]


def extract_text_from_resume(content: bytes, filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        try:
            import PyPDF2

            reader = PyPDF2.PdfReader(io.BytesIO(content))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n".join(pages)
        except Exception:
            return content.decode("utf-8", errors="ignore")

    if lower.endswith(".docx"):
        try:
            import docx

            document = docx.Document(io.BytesIO(content))
            return "\n".join([p.text for p in document.paragraphs if p.text.strip()])
        except Exception:
            return content.decode("utf-8", errors="ignore")

    return content.decode("utf-8", errors="ignore")


def extract_skills(resume_text: str) -> List[str]:
    found = set()
    for skill in SKILL_CANDIDATES:
        if re.search(rf"\b{re.escape(skill)}\b", resume_text, re.I):
            found.add(skill)
    return sorted(found)


def extract_experience(resume_text: str) -> float:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(years|yrs|year)\b", resume_text, re.I)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return USER_PROFILE.get("experience", 0)
    return USER_PROFILE.get("experience", 0)


def build_profile(resume_text: str) -> dict:
    return {
        "name": USER_PROFILE.get("name", "Candidate"),
        "experience": extract_experience(resume_text),
        "skills": extract_skills(resume_text) or USER_PROFILE.get("skills", []),
        "target_roles": USER_PROFILE.get("target_roles", []),
        "locations": USER_PROFILE.get("locations", []),
    }


def compact_text(text: Optional[str]) -> str:
    return (text or "").strip()


@app.get("/")
async def home(request: Request):
    return render_template(
        "index.html",
        {
            "resume_text": "",
            "profile": None,
            "jobs": [],
            "evaluation": None,
            "message": None,
            "job_description": "",
            "keyword": "",
        },
    )


@app.post("/upload")
async def upload_resume(request: Request, resume_file: UploadFile = File(...)):
    content = await resume_file.read()
    resume_text = extract_text_from_resume(content, resume_file.filename)
    profile = build_profile(resume_text)

    return render_template(
        "index.html",
        {
            "resume_text": resume_text,
            "profile": profile,
            "jobs": [],
            "evaluation": None,
            "message": "Resume uploaded and analyzed.",
            "job_description": "",
            "keyword": "",
        },
    )


@app.post("/evaluate")
async def evaluate_job(
    request: Request,
    job_description: str = Form(""),
    resume_text: str = Form(""),
):
    resume_text = compact_text(resume_text)
    if not resume_text:
        return RedirectResponse(url="/", status_code=303)

    profile = build_profile(resume_text)
    ats_score = calculate_ats(job_description, profile)
    visa = detect_visa(job_description)
    ai_analysis = analyze_job_ai(job_description, profile)
    cover_letter = generate_cover_letter(job_description, profile)
    recruiter_message = generate_recruiter_message(job_description, profile)

    evaluation = {
        "ats_score": ats_score,
        "visa": visa,
        "ai_analysis": ai_analysis,
        "cover_letter": cover_letter,
        "recruiter_message": recruiter_message,
    }

    return render_template(
        "index.html",
        {
            "resume_text": resume_text,
            "profile": profile,
            "jobs": [],
            "evaluation": evaluation,
            "job_description": job_description,
            "message": "Job description evaluated successfully.",
            "keyword": "",
        },
    )


@app.post("/search")
async def search_jobs(
    request: Request,
    resume_text: str = Form(""),
    keyword: str = Form(""),
):
    resume_text = compact_text(resume_text)
    profile = build_profile(resume_text)
    search_keywords = [keyword] if keyword.strip() else None
    jobs = scrape_linkedin_jobs(search_keywords=search_keywords)

    for job in jobs:
        job_description = job.get("description") or f"{job['title']} {job['company']} {job['location']}"
        job["ats_score"] = calculate_ats(job_description, profile)
        job["needs_match"] = job["ats_score"] < 70

    return render_template(
        "index.html",
        {
            "resume_text": resume_text,
            "profile": profile,
            "jobs": jobs,
            "evaluation": None,
            "keyword": keyword,
            "message": f"Found {len(jobs)} jobs for '{keyword or 'default keywords'}'.",
            "job_description": "",
        },
    )


@app.post("/generate-match")
async def generate_match(
    request: Request,
    resume_text: str = Form(""),
    job_link: str = Form(""),
    title: str = Form(""),
    company: str = Form(""),
    location: str = Form(""),
    description: str = Form(""),
):
    resume_text = compact_text(resume_text)
    if not resume_text:
        return RedirectResponse(url="/", status_code=303)

    profile = build_profile(resume_text)
    job_text = description or f"{title} {company} {location} {job_link}"
    ats_score = calculate_ats(job_text, profile)
    matching_resume = generate_matching_resume(job_text, resume_text, profile)

    job = {
        "title": title,
        "company": company,
        "location": location,
        "link": job_link,
        "description": description,
        "ats_score": ats_score,
        "needs_match": ats_score < 70,
    }

    return render_template(
        "index.html",
        {
            "resume_text": resume_text,
            "profile": profile,
            "jobs": [job],
            "evaluation": {
                "ats_score": ats_score,
                "matching_resume": matching_resume,
            },
            "message": f"Generated matching resume for {title} at {company}.",
            "keyword": "",
            "job_description": description,
        },
    )


@app.post("/apply")
async def apply_job(
    request: Request,
    resume_text: str = Form(""),
    job_link: str = Form(""),
    title: str = Form(""),
    company: str = Form(""),
    location: str = Form(""),
    description: str = Form(""),
):
    resume_text = compact_text(resume_text)
    profile = build_profile(resume_text)
    job_text = description or f"{title} {company} {location} {job_link}"
    ats_score = calculate_ats(job_text, profile)
    matching_resume = None
    if ats_score < 70:
        matching_resume = generate_matching_resume(job_text, resume_text, profile)

    result = auto_easy_apply(job_link, title, company)
    message = f"{result} ATS score: {ats_score}."

    job = {
        "title": title,
        "company": company,
        "location": location,
        "link": job_link,
        "description": description,
        "ats_score": ats_score,
        "needs_match": ats_score < 70,
    }

    evaluation = {
        "ats_score": ats_score,
        "matching_resume": matching_resume,
        "auto_apply_note": result,
    }

    return render_template(
        "index.html",
        {
            "resume_text": resume_text,
            "profile": profile,
            "jobs": [job],
            "evaluation": evaluation,
            "message": message,
            "keyword": "",
            "job_description": description,
        },
    )
