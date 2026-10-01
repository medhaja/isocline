"""Workflow template library for everyday roles.

Each template is a declarative spec turned into a normal workflow graph (inputs -> agents -> output), built with the
model the user picks when creating the workflow. Shapes:

  chain     inputs -> step 1 -> step 2 -> ... -> report
  parallel  inputs -> [research ->] parallel(specialists) -> merge -> writer -> report

`approval=True` inserts a Human Approval node before the final output (anything that will be sent, published or used
to make a decision about a person). Templates are starting points: every node is editable after creation.

Contributing a template: add a spec to TEMPLATES (keep prompts concrete, name the output format, state limits), then
run `pytest tests/unit/test_template_library.py`.
"""
from __future__ import annotations

from typing import Any

HONEST = ("If information is missing or uncertain, say so explicitly instead of inventing it. Use clear headings and "
          "concise bullet points where they help the reader.")
NOT_FINANCIAL_ADVICE = ("This is research and education, not financial advice. Never tell the user to buy, sell or hold, "
                        "and never give price targets. Present evidence, scenarios and risks so the user can decide.")
FAIR_HIRING = ("Assess only job-relevant skills, experience and evidence against the stated requirements. Ignore and never "
               "infer name, age, gender, ethnicity, nationality, religion, disability, marital or parental status, photos "
               "or employment gaps. Never make a final hiring decision: you prepare evidence for a human reviewer.")


def A(key: str, name: str, role: str, instructions: str, prompt: str, *, tools: list[str] | None = None,
      output_schema: dict | None = None, temperature: float = 0.3) -> dict:
    return {"key": key, "name": name, "role": role, "instructions": f"{instructions} {HONEST}", "prompt": prompt,
            "tools": tools or [], "output_schema": output_schema, "temperature": temperature}


def T(id_: str, name: str, category: str, description: str, inputs: list[tuple[str, str]], sample: dict[str, Any],
      shape: str, agents: list[dict], *, lead: dict | None = None, writer: dict | None = None, approval: str | None = None,
      output: str = "Report") -> dict:
    return {"id": id_, "name": name, "category": category, "description": description, "inputs": inputs,
            "sample_input": sample, "shape": shape, "agents": agents, "lead": lead, "writer": writer,
            "approval": approval, "output": output}


def I(field: str) -> str:
    return "{{input." + field + "}}"


SCORE = {"type": "object", "properties": {"score": {"type": "number", "minimum": 1, "maximum": 5},
                                          "evidence": {"type": "array", "items": {"type": "string"}},
                                          "concerns": {"type": "array", "items": {"type": "string"}}},
         "required": ["score", "evidence"]}

TEMPLATES: list[dict] = [
    # ------------------------------------------------------------------------------------------- Students
    T("student_study_planner", "Exam study planner", "Students",
      "Turns a syllabus and exam date into a day-by-day study plan with spaced repetition and practice checkpoints.",
      [("syllabus", "Syllabus or topic list"), ("exam_date", "Exam date and hours available per day")],
      {"syllabus": "Linear algebra: vectors, matrices, determinants, eigenvalues, linear transformations",
       "exam_date": "In 14 days, 2 hours per day"}, "chain", [
          A("analyze", "Syllabus analyst", "Learning scientist", "Break topics into prerequisite order and estimate difficulty.",
            f"Syllabus: {I('syllabus')}\nList the topics in prerequisite order with a difficulty (1-5) and estimated study hours each."),
          A("plan", "Study planner", "Study coach", "Build realistic plans using spaced repetition and active recall.",
            f"Time available: {I('exam_date')}\nTopic analysis:\n{{{{analyze.output}}}}\n\nWrite a day-by-day plan with review "
            "sessions, practice problems and two mock-exam checkpoints. End with tips for the last 48 hours."),
      ]),
    T("student_concept_tutor", "Concept explainer + quiz", "Students",
      "Explains a concept at your level with an analogy and worked example, then generates a quiz with answers.",
      [("concept", "Concept"), ("level", "Your level")],
      {"concept": "Bayes' theorem", "level": "First-year university student"}, "chain", [
          A("explain", "Tutor", "Patient tutor", "Explain from first principles, then build up. Use one analogy and one worked example.",
            f"Explain {I('concept')} to a {I('level')}."),
          A("quiz", "Quiz writer", "Assessment designer", "Write questions that test understanding, not memorisation.",
            "Based on this explanation:\n{{explain.output}}\n\nWrite 6 questions (3 multiple choice, 2 short answer, 1 applied "
            "problem), then an answer key with brief explanations."),
      ]),
    T("student_essay_coach", "Essay feedback coach", "Students",
      "Three reviewers (argument, evidence, writing) review your essay in parallel; a coach merges it into prioritised feedback.",
      [("essay", "Essay text"), ("assignment", "Assignment prompt or rubric")],
      {"assignment": "Argue whether cities should ban cars from their centres (800 words).",
       "essay": "Cities should ban cars from their centres because pollution harms health..."}, "parallel", [
          A("argument", "Argument reviewer", "Debate coach", "Assess thesis clarity, logic and counter-arguments.",
            f"Assignment: {I('assignment')}\nEssay:\n{I('essay')}\n\nReview the argument."),
          A("evidence", "Evidence reviewer", "Research librarian", "Assess whether claims are supported and sources are credible.",
            f"Essay:\n{I('essay')}\n\nList unsupported claims and suggest what evidence would support each."),
          A("style", "Writing reviewer", "Writing instructor", "Assess structure, clarity, grammar and tone. Quote examples.",
            f"Essay:\n{I('essay')}\n\nReview the writing."),
      ], writer=A("coach", "Feedback coach", "Encouraging teacher",
                  "Do not rewrite the essay for the student; guide them to improve it themselves.",
                  "Combine these reviews into feedback: 3 strengths, the 5 most important improvements in priority order, and "
                  "a checklist for the next draft.\n{{reviews.output}}")),
    T("student_paper_summarizer", "Research paper explainer", "Students",
      "Summarises a paper, explains its method in plain language and lists questions to discuss in class.",
      [("paper", "Paper text or abstract")],
      {"paper": "Abstract: We propose a transformer-based model for..."}, "chain", [
          A("summary", "Paper summarizer", "Research assistant", "Separate what the paper claims from what it shows.",
            f"Paper:\n{I('paper')}\n\nSummarise: problem, method, key results, limitations."),
          A("explain", "Plain-language explainer", "Science communicator", "Explain without jargon; define any term you must use.",
            "Explain the method and why it matters to a curious undergraduate:\n{{summary.output}}"),
          A("questions", "Discussion prompts", "Seminar leader", "Ask questions that probe assumptions and limitations.",
            "Write 8 discussion questions and 3 follow-up reading directions based on:\n{{summary.output}}"),
      ]),
    # ------------------------------------------------------------------------------------------- Job seekers
    T("job_resume_tailor", "Resume tailor for a job", "Job seekers",
      "Maps your resume to a job description, finds gaps, and rewrites bullets to match (truthfully).",
      [("resume", "Your resume"), ("job_description", "Job description")],
      {"resume": "Software engineer, 4 years. Built payment APIs in Python...", "job_description": "Backend Engineer at Acme Corp..."},
      "chain", [
          A("match", "Requirements matcher", "Technical recruiter", "Be precise about what the resume does and does not show.",
            f"Job description:\n{I('job_description')}\n\nResume:\n{I('resume')}\n\nTable: requirement | evidence in resume | "
            "strength (strong/partial/missing)."),
          A("rewrite", "Resume writer", "Resume coach",
            "Rewrite bullets using action + impact + metric. Never invent experience, employers, titles or numbers.",
            "Using this analysis:\n{{match.output}}\n\nResume:\n" + I("resume") + "\n\nRewrite the summary and the 6 most "
            "relevant bullets for this job. Then list honest ways to address the missing requirements."),
      ], output="Tailored resume"),
    T("job_cover_letter", "Cover letter writer", "Job seekers",
      "Researches the company, then writes a specific, non-generic cover letter you approve before using.",
      [("company", "Company"), ("role", "Role"), ("resume", "Your resume")],
      {"company": "Acme Corp", "role": "Product Manager", "resume": "PM, 3 years, B2B SaaS, led onboarding redesign..."},
      "chain", [
          A("research", "Company researcher", "Career researcher", "Focus on products, mission, recent news and culture signals.",
            f"Research {I('company')} for a {I('role')} application.", tools=["web_search"]),
          A("letter", "Cover letter writer", "Career coach",
            "Under 350 words. Specific to the company. No clichés. Never invent experience.",
            f"Write a cover letter for {I('role')} at {I('company')}.\nCompany research:\n{{{{research.output}}}}\nResume:\n{I('resume')}",
            temperature=0.6),
      ], approval="Review the cover letter before you send it", output="Cover letter"),
    T("job_interview_prep", "Interview prep coach", "Job seekers",
      "Company research, likely questions (behavioural + technical) and STAR answer outlines from your experience.",
      [("company", "Company"), ("role", "Role"), ("background", "Your background")],
      {"company": "Acme Corp", "role": "Data Analyst", "background": "2 years of SQL and dashboards in retail analytics"},
      "parallel", [
          A("company_brief", "Company brief", "Career researcher", "Summarise what an interviewer expects candidates to know.",
            f"Brief on {I('company')} for a {I('role')} interview.", tools=["web_search"]),
          A("behavioural", "Behavioural questions", "Hiring manager", "Pick questions this role typically asks.",
            f"10 likely behavioural questions for {I('role')}, each with a STAR outline using: {I('background')}"),
          A("technical", "Technical questions", "Senior practitioner", "Match the role's level.",
            f"10 likely technical questions for {I('role')} with what a strong answer covers."),
      ], writer=A("pack", "Prep pack writer", "Interview coach", "Make it scannable the night before the interview.",
                  "Combine into a one-page interview prep pack plus 5 smart questions to ask the interviewer:\n{{reviews.output}}")),
    T("job_offer_compare", "Job offer comparison", "Job seekers",
      "Compares offers on total compensation, growth, risk and fit, and drafts a negotiation email.",
      [("offers", "Offers (salary, equity, benefits, notes)"), ("priorities", "What matters most to you")],
      {"offers": "Offer A: $120k, no equity, remote. Offer B: $105k + 0.1% equity, hybrid, startup.",
       "priorities": "Learning, stability, remote work"}, "chain", [
          A("compare", "Offer analyst", "Compensation analyst", "Show assumptions for equity and benefits valuation.",
            f"Offers:\n{I('offers')}\nPriorities: {I('priorities')}\nCompare in a table and score each against the priorities."),
          A("negotiate", "Negotiation coach", "Negotiation coach", "Polite, specific, grounded in market data the user supplies.",
            "Based on:\n{{compare.output}}\nDraft a short negotiation email for the preferred offer and list 3 fallback asks."),
      ]),
    # ------------------------------------------------------------------------------------------- Interviewers
    T("interviewer_question_kit", "Structured interview kit", "Interviewers",
      "Builds a competency-based interview plan with questions, follow-ups and a scoring rubric from a job description.",
      [("job_description", "Job description"), ("stage", "Interview stage and length")],
      {"job_description": "Senior Backend Engineer: distributed systems, Python, mentoring", "stage": "Technical round, 60 minutes"},
      "chain", [
          A("competencies", "Competency mapper", "Hiring manager", "Pick 4-6 competencies that predict success in the role.",
            f"From this job description, list the competencies to assess and why:\n{I('job_description')}"),
          A("kit", "Interview kit writer", "Structured interviewing expert",
            f"Every candidate gets the same questions and rubric. {FAIR_HIRING}",
            f"Stage: {I('stage')}\nCompetencies:\n{{{{competencies.output}}}}\n\nWrite: timed agenda, 2 questions per competency "
            "with follow-ups, and a 1-5 rubric with observable anchors for each score."),
      ], output="Interview kit"),
    T("interviewer_scorecard", "Candidate evaluation scorecard", "Interviewers",
      "Scores interview notes against the rubric per competency (structured JSON), flags missing evidence, then a human signs off.",
      [("rubric", "Rubric / competencies"), ("notes", "Interview notes")],
      {"rubric": "System design, coding quality, communication, collaboration", "notes": "Candidate designed a rate limiter..."},
      "parallel", [
          A("technical", "Technical evidence", "Technical interviewer", FAIR_HIRING,
            f"Rubric: {I('rubric')}\nNotes:\n{I('notes')}\nScore the technical competencies only, citing notes.", output_schema=SCORE),
          A("behavioural", "Behavioural evidence", "Behavioural interviewer", FAIR_HIRING,
            f"Rubric: {I('rubric')}\nNotes:\n{I('notes')}\nScore communication and collaboration only, citing notes.", output_schema=SCORE),
      ], writer=A("summary", "Debrief writer", "Hiring panel chair", FAIR_HIRING,
                  "Write a debrief: evidence per competency, where evidence is missing, and questions for the next round. "
                  "No hire/no-hire decision.\n{{reviews.output}}"),
      approval="Interviewer sign-off on the evaluation", output="Scorecard"),
    T("interviewer_take_home", "Take-home assignment designer", "Interviewers",
      "Designs a realistic, time-boxed take-home task with a grading guide and a reviewer checklist.",
      [("role", "Role and level"), ("skills", "Skills to assess")],
      {"role": "Mid-level frontend engineer", "skills": "React state management, accessibility, testing"}, "chain", [
          A("task", "Task designer", "Engineering manager", "Respect candidates' time: 3 hours maximum. Realistic, not trick questions.",
            f"Design a take-home for {I('role')} assessing {I('skills')}: brief, starter materials, deliverables, time box."),
          A("guide", "Grading guide", "Bar raiser", FAIR_HIRING,
            "Write a grading guide with criteria, what good/great looks like, and red flags for:\n{{task.output}}"),
      ]),
    # ------------------------------------------------------------------------------------------- HR
    T("hr_job_description", "Inclusive job description writer", "HR",
      "Drafts a job description, then reviews it for biased language and unnecessary requirements before approval.",
      [("role", "Role"), ("details", "Team, responsibilities, must-haves")],
      {"role": "Customer Success Manager", "details": "B2B SaaS, 30 accounts, renewals, onboarding; must have 2+ years in CS"},
      "chain", [
          A("draft", "JD writer", "Talent partner", "Clear responsibilities, outcomes after 6 months, and must-have vs nice-to-have.",
            f"Write a job description for {I('role')}.\nDetails: {I('details')}"),
          A("review", "Inclusion reviewer", "Inclusive-hiring specialist",
            "Flag gendered or exclusionary wording, jargon, and requirements that are not truly necessary. Suggest replacements.",
            "Review and return the improved job description followed by a change log:\n{{draft.output}}"),
      ], approval="HR approval before posting", output="Job description"),
    T("hr_resume_screening", "Resume screening assistant (human decides)", "HR",
      "Compares a resume to must-have requirements with evidence, flags what to verify, and routes to a recruiter. Never auto-rejects.",
      [("requirements", "Must-have and nice-to-have requirements"), ("resume", "Resume")],
      {"requirements": "Must: 2+ years customer support, CRM experience. Nice: SaaS, Spanish",
       "resume": "Support specialist at a retail company for 3 years, Zendesk, ..."}, "chain", [
          A("evidence", "Evidence mapper", "Recruiter", FAIR_HIRING,
            f"Requirements:\n{I('requirements')}\nResume:\n{I('resume')}\nFor each requirement: evidence found (quote), or 'not shown'."),
          A("summary", "Screening summary", "Recruiter", FAIR_HIRING,
            "Summarise for a human recruiter: requirements met, not shown (to verify in a call, not reasons to reject), and 3 "
            "screening-call questions.\n{{evidence.output}}"),
      ], approval="Recruiter reviews and decides", output="Screening summary"),
    T("hr_onboarding_plan", "30-60-90 onboarding plan", "HR",
      "Creates a role-specific onboarding plan with first-week schedule, milestones and buddy checklist.",
      [("role", "Role"), ("team", "Team and tools")],
      {"role": "Junior Data Engineer", "team": "Data platform team; Airflow, dbt, Snowflake; manager: Priya"}, "chain", [
          A("plan", "Onboarding designer", "People operations partner", "Concrete, measurable milestones; include social onboarding.",
            f"30-60-90 day plan for {I('role')} joining {I('team')}, plus a first-week day-by-day schedule."),
          A("checklist", "Checklists", "HR coordinator", "Actionable checklists with owners.",
            "From this plan, write checklists for the manager, the buddy and the new hire:\n{{plan.output}}"),
      ]),
    T("hr_performance_review", "Performance review drafter", "HR",
      "Turns a manager's notes and goals into a balanced, evidence-based review draft for the manager to edit.",
      [("goals", "Goals for the period"), ("notes", "Manager notes and examples")],
      {"goals": "Ship onboarding v2; reduce ticket backlog 30%", "notes": "Shipped onboarding v2 two weeks late; backlog -35%..."},
      "chain", [
          A("assess", "Goal assessor", "Performance coach",
            "Evidence-based and specific. Separate impact from effort. Avoid personality judgements.",
            f"Goals:\n{I('goals')}\nNotes:\n{I('notes')}\nAssess each goal with evidence."),
          A("draft", "Review writer", "Manager coach", "Balanced tone; strengths, growth areas with examples, next-period goals.",
            "Write the review draft:\n{{assess.output}}"),
      ], approval="Manager edits and approves", output="Review draft"),
    T("hr_policy_answer", "Policy question answerer", "HR",
      "Answers an employee question strictly from the policy text you paste, citing sections, and escalates what it can't answer.",
      [("policy", "Policy text"), ("question", "Employee question")],
      {"policy": "Section 4.2 Parental leave: 16 weeks paid for primary caregivers...", "question": "How much leave do I get as a second parent?"},
      "chain", [
          A("answer", "Policy assistant", "HR business partner",
            "Answer only from the policy text; quote the section. If the policy does not cover it, say so and recommend "
            "contacting HR. This is not legal advice.",
            f"Policy:\n{I('policy')}\n\nQuestion: {I('question')}"),
      ], approval="HR checks the answer before sending", output="Answer"),
    # ------------------------------------------------------------------------------------------- Content creators
    T("creator_youtube_package", "YouTube video package", "Content creators",
      "Research, script with hook and chapters, 10 titles, thumbnail concepts and description, in one run.",
      [("topic", "Video topic"), ("audience", "Audience and length")],
      {"topic": "How durable execution makes AI agents reliable", "audience": "Developers, 10 minutes"}, "parallel", [
          A("script", "Scriptwriter", "YouTube scriptwriter", "Hook in the first 15 seconds, chapters, pattern interrupts, clear CTA.",
            f"Write a script about {I('topic')} for {I('audience')} with timestamps.", temperature=0.7),
          A("titles", "Title & thumbnail", "YouTube strategist", "Curiosity without clickbait; titles under 60 characters.",
            f"10 titles and 5 thumbnail concepts (text overlay + visual) for {I('topic')}.", temperature=0.8),
          A("seo", "Description & tags", "YouTube SEO specialist", "Natural keywords, no stuffing.",
            f"Video description with chapters placeholder, 15 tags and 3 pinned-comment ideas for {I('topic')}."),
      ], lead=A("research", "Topic researcher", "Researcher", "Find the key facts, angles and common misconceptions.",
                f"Research {I('topic')} for {I('audience')}.", tools=["web_search"]),
      writer=A("package", "Producer", "Video producer", "Assemble a clean production doc.",
               "Assemble the final video package:\n{{reviews.output}}")),
    T("creator_blog_pipeline", "SEO blog post pipeline", "Content creators",
      "Research → outline → draft → SEO/fact review, with your approval before it's final.",
      [("topic", "Topic"), ("keyword", "Target keyword")],
      {"topic": "Choosing a vector database", "keyword": "pgvector vs dedicated vector database"}, "chain", [
          A("research", "Researcher", "Researcher", "Collect facts with sources.", f"Research {I('topic')}.", tools=["web_search"]),
          A("outline", "Outliner", "Content strategist", "Match search intent.",
            f"Outline an article targeting '{I('keyword')}' from:\n{{{{research.output}}}}"),
          A("draft", "Writer", "Senior writer", "Clear, practical, no fluff. 1200-1500 words.",
            "Write the article from this outline:\n{{outline.output}}\nFacts:\n{{research.output}}", temperature=0.6),
          A("edit", "SEO & fact editor", "Editor", "Check claims against the research; flag anything unsupported.",
            f"Edit for accuracy, readability and the keyword '{I('keyword')}'. Return the final article, meta title and meta "
            "description.\n{{draft.output}}"),
      ], approval="Approve before publishing", output="Article"),
    T("creator_repurpose", "Repurpose one piece everywhere", "Content creators",
      "Turns one article or transcript into a LinkedIn post, an X thread, a newsletter section and short-video hooks, in parallel.",
      [("content", "Original content")],
      {"content": "Transcript: today we talk about why most AI agent demos fail in production..."}, "parallel", [
          A("linkedin", "LinkedIn post", "LinkedIn ghostwriter", "Strong first line, short paragraphs, one CTA.",
            f"LinkedIn post from:\n{I('content')}", temperature=0.7),
          A("thread", "X thread", "Social media writer", "8-10 posts, each standalone, no hashtags spam.",
            f"X thread from:\n{I('content')}", temperature=0.7),
          A("newsletter", "Newsletter section", "Newsletter editor", "Conversational, 250 words, one link placeholder.",
            f"Newsletter section from:\n{I('content')}"),
          A("shorts", "Short-video hooks", "Short-form video producer", "5 hooks + 30-second scripts.",
            f"Short-video hooks and scripts from:\n{I('content')}", temperature=0.8),
      ], writer=A("bundle", "Content bundle", "Content manager", "Keep each piece intact; add a posting schedule.",
                  "Bundle these pieces with a suggested posting schedule:\n{{reviews.output}}"),
      approval="Approve before posting"),
    T("creator_content_calendar", "30-day content calendar", "Content creators",
      "Builds a month of content ideas mapped to pillars, formats and goals.",
      [("niche", "Niche and audience"), ("goals", "Goals")],
      {"niche": "Personal finance for students", "goals": "Grow Instagram to 10k, launch a budgeting template"}, "chain", [
          A("pillars", "Strategist", "Content strategist", "Pillars must serve the goals.",
            f"Define 4 content pillars for {I('niche')} given goals: {I('goals')}"),
          A("calendar", "Calendar planner", "Social media manager", "Mix formats; include 2 launch pushes.",
            "Create a 30-day calendar table (day | pillar | format | hook | CTA) from:\n{{pillars.output}}"),
      ]),
    # ------------------------------------------------------------------------------------------- Managers
    T("manager_one_on_one", "1:1 meeting prep", "Managers",
      "Prepares a 1:1 agenda from recent notes: wins to recognise, blockers, growth topics and questions.",
      [("person", "Report's name and role"), ("notes", "Recent notes, updates, concerns")],
      {"person": "Sam, backend engineer", "notes": "Shipped search API; seems stressed about on-call; wants to lead a project"},
      "chain", [
          A("agenda", "1:1 coach", "Engineering manager coach", "Person-first, specific, and actionable.",
            f"Prepare a 1:1 for {I('person')} from:\n{I('notes')}\nAgenda, recognition, 5 open questions, follow-ups to track."),
      ], output="1:1 agenda"),
    T("manager_status_report", "Weekly status report", "Managers",
      "Turns messy notes into an executive status update: progress, risks, decisions needed.",
      [("notes", "This week's notes"), ("audience", "Audience")],
      {"notes": "API migration 70% done, payments bug fixed, hiring: 1 offer out, risk: vendor contract delay",
       "audience": "VP Engineering"}, "chain", [
          A("extract", "Notes analyst", "Chief of staff", "Separate facts, risks and decisions.",
            f"Extract progress, risks (with owner), decisions needed and asks from:\n{I('notes')}"),
          A("report", "Status writer", "Chief of staff", "Red/amber/green per workstream; under 250 words.",
            f"Write the weekly status for {I('audience')} from:\n{{{{extract.output}}}}"),
      ], output="Status report"),
    T("manager_risk_review", "Project risk review", "Managers",
      "Parallel review of schedule, technical and people risks with mitigations and a RAID log.",
      [("project", "Project description and plan")],
      {"project": "Migrating billing to a new provider by Q3; 4 engineers; dependency on finance team sign-off"}, "parallel", [
          A("schedule", "Schedule risks", "Delivery manager", "Look for critical-path and dependency risks.",
            f"Schedule and dependency risks in:\n{I('project')}"),
          A("technical", "Technical risks", "Staff engineer", "Look for integration, data and rollback risks.",
            f"Technical risks in:\n{I('project')}"),
          A("people", "People risks", "Engineering manager", "Look for capacity, knowledge concentration and stakeholder risks.",
            f"People and stakeholder risks in:\n{I('project')}"),
      ], writer=A("raid", "RAID log", "Program manager", "Likelihood x impact; each risk gets an owner and mitigation.",
                  "Build a RAID log and top-5 mitigations:\n{{reviews.output}}")),
    T("manager_meeting_actions", "Meeting notes → action items", "Managers",
      "Extracts decisions, action items with owners and dates, and drafts the follow-up email.",
      [("transcript", "Meeting notes or transcript")],
      {"transcript": "Priya: we'll launch on the 12th. Tom will update the docs by Friday..."}, "chain", [
          A("extract", "Action extractor", "Executive assistant", "Only what was actually said; mark unclear owners as 'unassigned'.",
            f"Decisions, action items (owner, due date) and open questions from:\n{I('transcript')}",
            output_schema={"type": "object", "properties": {
                "decisions": {"type": "array", "items": {"type": "string"}},
                "actions": {"type": "array", "items": {"type": "object", "properties": {
                    "task": {"type": "string"}, "owner": {"type": "string"}, "due": {"type": "string"}}}},
                "open_questions": {"type": "array", "items": {"type": "string"}}}, "required": ["actions"]}),
          A("email", "Follow-up email", "Executive assistant", "Short and scannable.",
            "Draft the follow-up email from:\n{{extract.output}}"),
      ], approval="Review before sending", output="Follow-up"),
    # ------------------------------------------------------------------------------------------- Stock traders / investors
    T("trader_stock_research", "Stock research brief (not advice)", "Stock traders & investors",
      "Fundamentals, recent news and risks researched in parallel, combined into a balanced brief. No buy/sell calls.",
      [("ticker", "Company or ticker"), ("horizon", "Your time horizon")],
      {"ticker": "Example Corp (EXMP)", "horizon": "Long term (3+ years)"}, "parallel", [
          A("fundamentals", "Fundamentals analyst", "Equity research analyst", NOT_FINANCIAL_ADVICE,
            f"Business model, revenue drivers, margins, balance sheet and valuation context for {I('ticker')}.", tools=["web_search"]),
          A("news", "News & catalysts", "Market news analyst", NOT_FINANCIAL_ADVICE,
            f"Recent news, upcoming catalysts and sentiment for {I('ticker')} with dates.", tools=["web_search"]),
          A("risks", "Risk analyst", "Risk analyst", NOT_FINANCIAL_ADVICE,
            f"Key risks for {I('ticker')}: business, competitive, regulatory, balance sheet, concentration."),
      ], writer=A("brief", "Research brief", "Investment research editor", NOT_FINANCIAL_ADVICE,
                  f"Write a balanced brief for a {I('horizon')} horizon: bull case, bear case, key metrics to watch, open "
                  "questions. Start with 'Research only, not financial advice.'\n{{reviews.output}}")),
    T("trader_earnings_call", "Earnings call analyzer", "Stock traders & investors",
      "Extracts guidance, KPIs, tone shifts and analyst concerns from an earnings call transcript.",
      [("transcript", "Earnings call transcript")],
      {"transcript": "CEO: Revenue grew 18% year over year... CFO: We now expect full-year margins of..."}, "chain", [
          A("extract", "Numbers & guidance", "Equity analyst", NOT_FINANCIAL_ADVICE,
            f"Extract reported KPIs, guidance changes and management commitments from:\n{I('transcript')}"),
          A("tone", "Tone & Q&A", "Buy-side analyst", NOT_FINANCIAL_ADVICE,
            f"What changed in tone vs typical language, what analysts pushed on, what was avoided:\n{I('transcript')}"),
          A("summary", "Earnings summary", "Research editor", NOT_FINANCIAL_ADVICE,
            "One-page summary with what to watch next quarter:\n{{extract.output}}\n{{tone.output}}"),
      ]),
    T("trader_portfolio_risk", "Portfolio risk & diversification check", "Stock traders & investors",
      "Computes weights, concentration and sector exposure in the Python sandbox, then explains the risks in plain language.",
      [("positions", "Positions JSON: [{ticker, sector, value}]")],
      {"positions": [{"ticker": "AAA", "sector": "Tech", "value": 5000}, {"ticker": "BBB", "sector": "Tech", "value": 3000},
                     {"ticker": "CCC", "sector": "Energy", "value": 2000}]}, "python", [
          A("explain", "Risk explainer", "Portfolio risk educator", NOT_FINANCIAL_ADVICE,
            "Explain these portfolio statistics: concentration, sector exposure and diversification considerations. "
            "No recommendations to buy or sell.\n{{stats.output}}"),
      ]),
    T("trader_journal_review", "Trading journal reviewer", "Stock traders & investors",
      "Finds patterns in your trade journal: rule breaks, emotional trades, best/worst setups, and process improvements.",
      [("journal", "Trade journal entries")],
      {"journal": "Mar 3: bought breakout, sold -4% on fear... Mar 5: followed plan, +6%..."}, "chain", [
          A("patterns", "Pattern finder", "Trading performance coach", NOT_FINANCIAL_ADVICE,
            f"Find patterns in process and behaviour (not predictions) in:\n{I('journal')}"),
          A("plan", "Process plan", "Trading performance coach", NOT_FINANCIAL_ADVICE,
            "Write 5 process rules and a pre-trade checklist from:\n{{patterns.output}}"),
      ]),
    # ------------------------------------------------------------------------------------------- CEOs & founders
    T("ceo_board_update", "Board / investor update", "CEOs & founders",
      "Drafts a crisp board or investor update from metrics and notes, with asks, and waits for your approval.",
      [("metrics", "Key metrics this period"), ("notes", "Highlights, lowlights, asks")],
      {"metrics": "ARR $2.1M (+12% QoQ), burn $180k/mo, runway 20 months", "notes": "Closed 3 enterprise deals; lost head of sales"},
      "chain", [
          A("draft", "Update writer", "Chief of staff", "Lead with the headline; show lowlights honestly; end with specific asks.",
            f"Board update from metrics:\n{I('metrics')}\nNotes:\n{I('notes')}"),
          A("critique", "Board-member critic", "Experienced board member", "Ask what a sceptical director would ask.",
            "List the 5 questions a board member will ask and tighten the update:\n{{draft.output}}"),
      ], approval="CEO approval before sending", output="Board update"),
    T("ceo_competitive_landscape", "Competitive landscape brief", "CEOs & founders",
      "Researches competitors in parallel (product, pricing, positioning) and synthesises threats and opportunities.",
      [("company", "Your company and product"), ("competitors", "Competitors")],
      {"company": "Acme Corp: workflow automation for SMBs", "competitors": "Globex Automate, Initech Flow"}, "parallel", [
          A("product", "Product comparison", "Product analyst", "Compare capabilities fairly.",
            f"Compare products of {I('competitors')} with {I('company')}.", tools=["web_search"]),
          A("pricing", "Pricing & packaging", "Pricing analyst", "Only publicly available information.",
            f"Pricing and packaging of {I('competitors')}.", tools=["web_search"]),
          A("positioning", "Positioning", "Brand strategist", "Messaging, target customers, recent moves.",
            f"Positioning and recent strategic moves of {I('competitors')}.", tools=["web_search"]),
      ], writer=A("brief", "Strategy brief", "Strategy consultant", "Actionable implications, not a data dump.",
                  "Synthesise: where we win, where we lose, threats, opportunities, 3 recommended moves.\n{{reviews.output}}")),
    T("ceo_strategy_options", "Strategy options memo", "CEOs & founders",
      "Frames a strategic decision, generates options, stress-tests them from finance/customer/operations views and writes a memo.",
      [("decision", "Decision to make"), ("context", "Context and constraints")],
      {"decision": "Should we expand to the EU next year?", "context": "12 people, $3M runway, 20% of leads from EU"}, "parallel", [
          A("finance", "Finance view", "CFO", "Quantify where possible; state assumptions.",
            f"Financial view on: {I('decision')}\nContext: {I('context')}"),
          A("customer", "Customer view", "Head of customer", "Ground in customer evidence.",
            f"Customer and market view on: {I('decision')}\nContext: {I('context')}"),
          A("ops", "Operations view", "COO", "Execution risks and requirements.",
            f"Operational view on: {I('decision')}\nContext: {I('context')}"),
      ], writer=A("memo", "Decision memo", "Strategy advisor", "Options with trade-offs, a recommendation, and what would change it.",
                  "Write a decision memo (Amazon 6-pager style, condensed):\n{{reviews.output}}"),
      approval="Leadership review"),
    T("founder_customer_discovery", "Customer interview synthesis", "CEOs & founders",
      "Synthesises customer interview notes into jobs-to-be-done, pains, quotes and product opportunities.",
      [("interviews", "Interview notes")],
      {"interviews": "Interview 1 (ops lead): we lose hours copying data between tools..."}, "chain", [
          A("themes", "Research synthesiser", "User researcher", "Evidence over opinions; quote participants.",
            f"Themes, jobs-to-be-done, pains and representative quotes from:\n{I('interviews')}"),
          A("opps", "Opportunity mapper", "Product strategist", "Prioritise by frequency and severity.",
            "Opportunity tree and the 3 riskiest assumptions to test next:\n{{themes.output}}"),
      ]),
    T("founder_pitch_narrative", "Pitch deck narrative", "CEOs & founders",
      "Builds a slide-by-slide pitch narrative and anticipates investor objections.",
      [("company", "What you do, traction, ask")],
      {"company": "Acme Corp: AI bookkeeping for freelancers; 800 paying users; raising $1.5M pre-seed"}, "chain", [
          A("story", "Narrative", "Pitch coach", "12 slides: problem, solution, why now, market, product, traction, model, "
            "competition, team, ask.", f"Slide-by-slide narrative with speaker notes for:\n{I('company')}", temperature=0.6),
          A("objections", "Investor objections", "Venture capitalist", "Be tough but fair.",
            "Top 10 investor objections and crisp answers:\n{{story.output}}"),
      ]),
    # ------------------------------------------------------------------------------------------- CTOs & engineering leaders
    T("cto_adr_review", "Architecture decision review", "CTOs & engineering leaders",
      "Reviews an architecture proposal from security, reliability, cost and team-fit angles and writes an ADR.",
      [("proposal", "Architecture proposal")],
      {"proposal": "Move from a monolith to event-driven microservices using Kafka for order processing"}, "parallel", [
          A("security", "Security review", "Security architect", "Threats, data flows, auth boundaries.", f"Security review:\n{I('proposal')}"),
          A("reliability", "Reliability review", "SRE lead", "Failure modes, observability, operability.",
            f"Reliability and operability review:\n{I('proposal')}"),
          A("cost", "Cost & team fit", "Engineering director", "Build/run cost, skills, migration effort.",
            f"Cost, skills and migration review:\n{I('proposal')}"),
      ], writer=A("adr", "ADR writer", "Principal engineer", "Standard ADR: context, decision, alternatives, consequences.",
                  "Write an ADR with a recommendation and conditions:\n{{reviews.output}}"),
      approval="CTO sign-off"),
    T("cto_build_vs_buy", "Build vs buy analysis", "CTOs & engineering leaders",
      "Compares building, buying and open-source options on cost, time, risk and strategic value.",
      [("capability", "Capability needed"), ("constraints", "Budget, team, timeline")],
      {"capability": "Internal feature-flag system", "constraints": "5 engineers, launch in 8 weeks, $20k/yr budget"}, "chain", [
          A("options", "Options researcher", "Solutions architect", "Include at least one open-source option.",
            f"Options to get {I('capability')}.", tools=["web_search"]),
          A("tco", "TCO analyst", "Engineering finance partner", "3-year total cost of ownership with assumptions.",
            f"TCO for each option given {I('constraints')}:\n{{{{options.output}}}}"),
          A("recommend", "Recommendation", "CTO advisor", "Decision matrix and a recommendation with exit criteria.",
            "Recommend an option:\n{{tco.output}}"),
      ]),
    T("cto_postmortem", "Incident postmortem drafter", "CTOs & engineering leaders",
      "Turns an incident timeline into a blameless postmortem with root causes and prioritised action items.",
      [("timeline", "Incident timeline and notes")],
      {"timeline": "14:02 deploy v2.3; 14:10 error rate 12%; 14:25 rollback; cause: missing DB index..."}, "chain", [
          A("analysis", "Root cause analyst", "SRE", "Blameless; systems over people; 5 whys.",
            f"Impact, timeline, contributing factors and root causes from:\n{I('timeline')}"),
          A("doc", "Postmortem writer", "Engineering manager", "Action items with owner role, priority and due date.",
            "Write the postmortem document:\n{{analysis.output}}"),
      ], approval="Review before publishing internally", output="Postmortem"),
    T("cto_vendor_evaluation", "Vendor / tool evaluation", "CTOs & engineering leaders",
      "Evaluates vendors against weighted criteria and produces a scored comparison and a proof-of-concept plan.",
      [("need", "What you need"), ("vendors", "Vendors to evaluate")],
      {"need": "Observability for 40 services, OpenTelemetry native", "vendors": "Vendor A, Vendor B, self-hosted stack"}, "chain", [
          A("criteria", "Criteria designer", "Platform lead", "Weighted, measurable criteria.",
            f"Weighted evaluation criteria for: {I('need')}"),
          A("score", "Evaluator", "Solutions architect", "Score with evidence; mark unknowns.",
            f"Score {I('vendors')} against:\n{{{{criteria.output}}}}", tools=["web_search"]),
          A("poc", "PoC planner", "Staff engineer", "2-week proof of concept with success criteria.",
            "PoC plan for the top two options:\n{{score.output}}"),
      ]),
    # ------------------------------------------------------------------------------------------- Developers
    T("dev_code_review", "Code review (3 reviewers)", "Developers",
      "Correctness, security and maintainability reviewers look at a diff in parallel; a lead merges findings by severity.",
      [("diff", "Code or diff"), ("context", "What the change does")],
      {"diff": "def get_user(id):\n    return db.execute(f'select * from users where id={id}')", "context": "User lookup endpoint"},
      "parallel", [
          A("correctness", "Correctness", "Senior engineer", "Bugs, edge cases, error handling.", f"Context: {I('context')}\n{I('diff')}"),
          A("security", "Security", "Application security engineer", "Injection, authz, secrets, unsafe input.",
            f"Context: {I('context')}\n{I('diff')}"),
          A("maintainability", "Maintainability", "Staff engineer", "Naming, structure, tests, readability.",
            f"Context: {I('context')}\n{I('diff')}"),
      ], writer=A("review", "Review lead", "Tech lead", "Group by severity (blocker/major/minor/nit) with suggested fixes.",
                  "Merge into one code review:\n{{reviews.output}}")),
    T("dev_pr_description", "PR description & release notes", "Developers",
      "Writes a clear pull-request description, testing notes and user-facing release notes from a diff.",
      [("diff", "Diff or change summary")],
      {"diff": "Added retry with exponential backoff to the HTTP client; new setting max_retries"}, "chain", [
          A("pr", "PR writer", "Senior engineer", "What/why/how, risks, testing done, rollout.", f"PR description for:\n{I('diff')}"),
          A("notes", "Release notes", "Developer advocate", "User-facing, benefit first, no internal jargon.",
            "Release notes entry from:\n{{pr.output}}"),
      ]),
    T("dev_bug_triage", "Bug report triage", "Developers",
      "Classifies a bug report, proposes likely causes and reproduction steps, and drafts the reply to the reporter.",
      [("report", "Bug report")],
      {"report": "App crashes when uploading a PDF larger than 20MB on Safari"}, "chain", [
          A("triage", "Triage engineer", "Support engineer", "Severity, component, missing information.",
            f"Triage:\n{I('report')}", output_schema={"type": "object", "properties": {
                "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]}, "component": {"type": "string"},
                "missing_info": {"type": "array", "items": {"type": "string"}}}, "required": ["severity", "component"]}),
          A("hypotheses", "Debugger", "Senior engineer", "Ranked hypotheses with how to confirm each.",
            f"Likely causes and reproduction steps for:\n{I('report')}\nTriage: {{{{triage.output}}}}"),
          A("reply", "Reporter reply", "Developer relations", "Friendly; ask only for the missing info.",
            "Reply to the reporter:\n{{triage.output}}"),
      ]),
    # ------------------------------------------------------------------------------------------- Sales & marketing
    T("sales_account_research", "Account research + outreach", "Sales & marketing",
      "Researches a prospect, maps pains to your product and drafts a personalised email you approve before sending.",
      [("prospect", "Prospect company and contact role"), ("offer", "What you sell")],
      {"prospect": "Globex Corp, Head of Operations", "offer": "Acme workflow automation that cuts manual data entry"}, "chain", [
          A("research", "Account researcher", "Sales development researcher", "Public information only.",
            f"Research {I('prospect')}: priorities, recent news, likely pains.", tools=["web_search"]),
          A("email", "Outreach writer", "Account executive", "Under 120 words, one clear ask, no fake familiarity.",
            f"Personalised first email offering {I('offer')} using:\n{{{{research.output}}}}", temperature=0.6),
      ], approval="Approve before sending", output="Outreach email"),
    T("sales_call_prep", "Sales call prep", "Sales & marketing",
      "Discovery questions, objection handling and a call plan tailored to the account.",
      [("account", "Account and stage"), ("notes", "What you know so far")],
      {"account": "Initech, second call (technical evaluation)", "notes": "Concerned about security review and migration effort"},
      "chain", [
          A("plan", "Call planner", "Sales coach", "MEDDICC-style gaps; tailored objections.",
            f"Call plan for {I('account')} given:\n{I('notes')}\nGoals, questions, objections with responses, next steps."),
      ]),
    T("marketing_campaign_brief", "Campaign brief + ad variants", "Sales & marketing",
      "Creates a campaign brief, then generates ad copy variants per channel for testing.",
      [("product", "Product"), ("audience", "Audience and goal")],
      {"product": "Acme budgeting app", "audience": "Students; goal: 5k sign-ups in a month"}, "chain", [
          A("brief", "Strategist", "Marketing strategist", "Insight, message, proof points, channels, KPIs.",
            f"Campaign brief for {I('product')} targeting {I('audience')}."),
          A("ads", "Copywriter", "Performance copywriter", "3 variants per channel; respect character limits.",
            "Ad variants for search, social and email from:\n{{brief.output}}", temperature=0.8),
      ], approval="Approve before launch"),
    # ------------------------------------------------------------------------------------------- Researchers, teachers, support, freelancers
    T("research_literature_review", "Literature review assistant", "Researchers",
      "Finds and summarises sources on a question, maps agreements and gaps, and suggests research directions.",
      [("question", "Research question")],
      {"question": "What interventions reduce hallucinations in retrieval-augmented generation?"}, "chain", [
          A("sources", "Source finder", "Research librarian", "Prefer peer-reviewed and primary sources; give citations.",
            f"Find and summarise key sources on: {I('question')}", tools=["web_search"]),
          A("synthesis", "Synthesiser", "Senior researcher", "Where sources agree, disagree, and what is untested.",
            "Synthesise:\n{{sources.output}}"),
          A("directions", "Gap finder", "Research advisor", "Feasible next studies.",
            "Research gaps and 5 study ideas from:\n{{synthesis.output}}"),
      ]),
    T("teacher_lesson_plan", "Lesson plan + worksheet", "Teachers",
      "Plans a lesson with objectives, activities and differentiation, plus a worksheet with answer key.",
      [("topic", "Topic"), ("class", "Grade/level and duration")],
      {"topic": "Photosynthesis", "class": "Grade 7, 45 minutes"}, "chain", [
          A("plan", "Lesson planner", "Experienced teacher", "Objectives, hook, activities, checks for understanding, differentiation.",
            f"Lesson plan on {I('topic')} for {I('class')}."),
          A("worksheet", "Worksheet", "Curriculum designer", "Mix recall and application; answer key at the end.",
            "Worksheet for:\n{{plan.output}}"),
      ]),
    T("support_ticket_reply", "Support ticket triage + reply", "Customer support",
      "Classifies a ticket, drafts an empathetic reply grounded in your help docs, and waits for an agent to approve.",
      [("ticket", "Customer ticket"), ("docs", "Relevant help-center text")],
      {"ticket": "I was charged twice this month and nobody answers!", "docs": "Duplicate charges are refunded within 5 days..."},
      "chain", [
          A("triage", "Triage", "Support lead", "Category, urgency, sentiment.", f"Triage:\n{I('ticket')}",
            output_schema={"type": "object", "properties": {"category": {"type": "string"},
                                                            "urgency": {"type": "string", "enum": ["urgent", "high", "normal", "low"]},
                                                            "sentiment": {"type": "string"}}, "required": ["category", "urgency"]}),
          A("reply", "Reply writer", "Senior support agent", "Empathetic, specific, only promises that the docs support.",
            f"Reply to:\n{I('ticket')}\nUsing only:\n{I('docs')}\nTriage: {{{{triage.output}}}}"),
      ], approval="Support agent approves before sending", output="Reply"),
    T("freelancer_proposal", "Client proposal writer", "Freelancers",
      "Turns a client brief into a scoped proposal with milestones, pricing options and assumptions.",
      [("brief", "Client brief"), ("rate", "Your rate and availability")],
      {"brief": "Need a Shopify store redesign with faster checkout, launch in 6 weeks", "rate": "$60/hour, 25 hours/week"},
      "chain", [
          A("scope", "Scoper", "Project manager", "Clarify deliverables, exclusions and risks.",
            f"Scope, milestones and clarifying questions for:\n{I('brief')}"),
          A("proposal", "Proposal writer", "Freelance consultant", "Three pricing options (fixed, milestone, retainer).",
            f"Proposal using rate {I('rate')}:\n{{{{scope.output}}}}"),
      ], approval="Review before sending", output="Proposal"),
]

PYTHON_PORTFOLIO_CODE = (
    "import json\n"
    "positions = INPUTS['positions']\n"
    "if isinstance(positions, str):\n    positions = json.loads(positions)\n"
    "total = sum(float(p['value']) for p in positions)\n"
    "weights = {p['ticker']: round(float(p['value']) / total, 4) for p in positions}\n"
    "sectors = {}\n"
    "for p in positions:\n    sectors[p['sector']] = sectors.get(p['sector'], 0) + float(p['value']) / total\n"
    "hhi = sum(w * w for w in weights.values())\n"
    "stats = {'total_value': total, 'weights': weights, 'sector_weights': {k: round(v, 4) for k, v in sectors.items()},\n"
    "         'largest_position': max(weights, key=weights.get), 'herfindahl_index': round(hhi, 4),\n"
    "         'effective_number_of_positions': round(1 / hhi, 2)}\n"
    "print(json.dumps(stats))\n"
    "with open('out/portfolio_stats.json', 'w') as f:\n    json.dump(stats, f, indent=2)\n"
)


def build(spec: dict, model: dict, builder_cls) -> dict:
    """Build the graph for a template spec. `builder_cls` is services.workflows._B."""
    b = builder_cls(model)
    col, prev = 0, []
    for row, (field, label) in enumerate(spec["inputs"]):
        prev.append(b.add(field, "input_text", label, col, row, field=field, label=label))
    col += 1

    def agent(a: dict, c: int, r: float) -> str:
        extra = {"name": a["name"], "role": a["role"], "instructions": a["instructions"], "tools": a["tools"],
                 "temperature": a["temperature"]}
        if a.get("output_schema"):
            extra["output_schema"] = a["output_schema"]
        return b.agent(a["key"], "custom", c, r, a["prompt"], **extra)

    def link_all(srcs, dst):
        for s in srcs:
            b.link(s, dst)

    if spec["shape"] == "python":
        py = b.add("stats", "tool_python", "Portfolio statistics", col, 0,
                   arguments={"code": PYTHON_PORTFOLIO_CODE, "inputs": {"positions": "{{input.positions}}"}}, timeout_seconds=60)
        link_all(prev, py)
        prev, col = [py], col + 1
        for a in spec["agents"]:
            nid = agent(a, col, 0)
            link_all(prev, nid)
            prev, col = [nid], col + 1
    elif spec["shape"] == "chain":
        for a in spec["agents"]:
            nid = agent(a, col, 0)
            link_all(prev, nid)
            prev, col = [nid], col + 1
    else:  # parallel
        if spec.get("lead"):
            nid = agent(spec["lead"], col, 0)
            link_all(prev, nid)
            prev, col = [nid], col + 1
        fan = b.add("fan_out", "parallel", "In parallel", col, 0)
        link_all(prev, fan)
        col += 1
        n = len(spec["agents"])
        branches = [agent(a, col, i - (n - 1) / 2) for i, a in enumerate(spec["agents"])]
        for br in branches:
            b.link(fan, br)
        col += 1
        merge = b.add("reviews", "merge", "Combine", col, 0, strategy="named")
        for br in branches:
            b.link(br, merge)
        prev, col = [merge], col + 1
        if spec.get("writer"):
            nid = agent(spec["writer"], col, 0)
            b.link(merge, nid)
            prev, col = [nid], col + 1
    handle = None
    if spec.get("approval"):
        ok = b.add("approval", "human_approval", "Human approval", col, 0, title=spec["approval"],
                   instructions="Edit if needed, then approve or reject.", allow_edit=True, max_wait_seconds=604800,
                   timeout_action="fail")
        link_all(prev, ok)
        prev, col, handle = [ok], col + 1, "approved"
    out = b.add("result", "output_report", spec["output"], col, 0, format="markdown")
    for s in prev:
        b.link(s, out, handle)
    return b.graph(max_llm_calls=30, max_cost=2.0)
