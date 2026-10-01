# Workflow templates

Isocline ships **47 role-based templates** plus 6 general ones. Open **Templates** in the UI, filter by role,
pick one, choose the model to use, and you get a normal workflow you can edit freely. Every template is tested: CI
creates each one and runs it end to end (`scripts/template_check.py`).

Templates that send, publish or decide something about a person end with a **Human approval** step. Investment
templates are research-only (no buy/sell calls or price targets). Hiring templates assess job-relevant evidence only and
never make the decision: a person does.

## Students

| Template | What it does | Inputs |
|---|---|---|
| **Exam study planner** | Turns a syllabus and exam date into a day-by-day study plan with spaced repetition and practice checkpoints. | Syllabus or topic list, Exam date and hours available per day |
| **Concept explainer + quiz** | Explains a concept at your level with an analogy and worked example, then generates a quiz with answers. | Concept, Your level |
| **Essay feedback coach** | Three reviewers (argument, evidence, writing) review your essay in parallel; a coach merges it into prioritised feedback. | Essay text, Assignment prompt or rubric |
| **Research paper explainer** | Summarises a paper, explains its method in plain language and lists questions to discuss in class. | Paper text or abstract |

## Job seekers

| Template | What it does | Inputs |
|---|---|---|
| **Resume tailor for a job** | Maps your resume to a job description, finds gaps, and rewrites bullets to match (truthfully). | Your resume, Job description |
| **Cover letter writer** | Researches the company, then writes a specific, non-generic cover letter you approve before using. Ends with human approval. | Company, Role, Your resume |
| **Interview prep coach** | Company research, likely questions (behavioural + technical) and STAR answer outlines from your experience. | Company, Role, Your background |
| **Job offer comparison** | Compares offers on total compensation, growth, risk and fit, and drafts a negotiation email. | Offers (salary, equity, benefits, notes), What matters most to you |

## Interviewers

| Template | What it does | Inputs |
|---|---|---|
| **Structured interview kit** | Builds a competency-based interview plan with questions, follow-ups and a scoring rubric from a job description. | Job description, Interview stage and length |
| **Candidate evaluation scorecard** | Scores interview notes against the rubric per competency (structured JSON), flags missing evidence, then a human signs off. Ends with human approval. | Rubric / competencies, Interview notes |
| **Take-home assignment designer** | Designs a realistic, time-boxed take-home task with a grading guide and a reviewer checklist. | Role and level, Skills to assess |

## HR

| Template | What it does | Inputs |
|---|---|---|
| **Inclusive job description writer** | Drafts a job description, then reviews it for biased language and unnecessary requirements before approval. Ends with human approval. | Role, Team, responsibilities, must-haves |
| **Resume screening assistant (human decides)** | Compares a resume to must-have requirements with evidence, flags what to verify, and routes to a recruiter. Never auto-rejects. Ends with human approval. | Must-have and nice-to-have requirements, Resume |
| **30-60-90 onboarding plan** | Creates a role-specific onboarding plan with first-week schedule, milestones and buddy checklist. | Role, Team and tools |
| **Performance review drafter** | Turns a manager's notes and goals into a balanced, evidence-based review draft for the manager to edit. Ends with human approval. | Goals for the period, Manager notes and examples |
| **Policy question answerer** | Answers an employee question strictly from the policy text you paste, citing sections, and escalates what it can't answer. Ends with human approval. | Policy text, Employee question |

## Content creators

| Template | What it does | Inputs |
|---|---|---|
| **YouTube video package** | Research, script with hook and chapters, 10 titles, thumbnail concepts and description, in one run. | Video topic, Audience and length |
| **SEO blog post pipeline** | Research → outline → draft → SEO/fact review, with your approval before it's final. Ends with human approval. | Topic, Target keyword |
| **Repurpose one piece everywhere** | Turns one article or transcript into a LinkedIn post, an X thread, a newsletter section and short-video hooks, in parallel. Ends with human approval. | Original content |
| **30-day content calendar** | Builds a month of content ideas mapped to pillars, formats and goals. | Niche and audience, Goals |

## Managers

| Template | What it does | Inputs |
|---|---|---|
| **1:1 meeting prep** | Prepares a 1:1 agenda from recent notes: wins to recognise, blockers, growth topics and questions. | Report's name and role, Recent notes, updates, concerns |
| **Weekly status report** | Turns messy notes into an executive status update: progress, risks, decisions needed. | This week's notes, Audience |
| **Project risk review** | Parallel review of schedule, technical and people risks with mitigations and a RAID log. | Project description and plan |
| **Meeting notes → action items** | Extracts decisions, action items with owners and dates, and drafts the follow-up email. Ends with human approval. | Meeting notes or transcript |

## Stock traders & investors

| Template | What it does | Inputs |
|---|---|---|
| **Stock research brief (not advice)** | Fundamentals, recent news and risks researched in parallel, combined into a balanced brief. No buy/sell calls. | Company or ticker, Your time horizon |
| **Earnings call analyzer** | Extracts guidance, KPIs, tone shifts and analyst concerns from an earnings call transcript. | Earnings call transcript |
| **Portfolio risk & diversification check** | Computes weights, concentration and sector exposure in the Python sandbox, then explains the risks in plain language. | Positions JSON: [{ticker, sector, value}] |
| **Trading journal reviewer** | Finds patterns in your trade journal: rule breaks, emotional trades, best/worst setups, and process improvements. | Trade journal entries |

## CEOs & founders

| Template | What it does | Inputs |
|---|---|---|
| **Board / investor update** | Drafts a crisp board or investor update from metrics and notes, with asks, and waits for your approval. Ends with human approval. | Key metrics this period, Highlights, lowlights, asks |
| **Competitive landscape brief** | Researches competitors in parallel (product, pricing, positioning) and synthesises threats and opportunities. | Your company and product, Competitors |
| **Strategy options memo** | Frames a strategic decision, generates options, stress-tests them from finance/customer/operations views and writes a memo. Ends with human approval. | Decision to make, Context and constraints |
| **Customer interview synthesis** | Synthesises customer interview notes into jobs-to-be-done, pains, quotes and product opportunities. | Interview notes |
| **Pitch deck narrative** | Builds a slide-by-slide pitch narrative and anticipates investor objections. | What you do, traction, ask |

## CTOs & engineering leaders

| Template | What it does | Inputs |
|---|---|---|
| **Architecture decision review** | Reviews an architecture proposal from security, reliability, cost and team-fit angles and writes an ADR. Ends with human approval. | Architecture proposal |
| **Build vs buy analysis** | Compares building, buying and open-source options on cost, time, risk and strategic value. | Capability needed, Budget, team, timeline |
| **Incident postmortem drafter** | Turns an incident timeline into a blameless postmortem with root causes and prioritised action items. Ends with human approval. | Incident timeline and notes |
| **Vendor / tool evaluation** | Evaluates vendors against weighted criteria and produces a scored comparison and a proof-of-concept plan. | What you need, Vendors to evaluate |

## Developers

| Template | What it does | Inputs |
|---|---|---|
| **Code review (3 reviewers)** | Correctness, security and maintainability reviewers look at a diff in parallel; a lead merges findings by severity. | Code or diff, What the change does |
| **PR description & release notes** | Writes a clear pull-request description, testing notes and user-facing release notes from a diff. | Diff or change summary |
| **Bug report triage** | Classifies a bug report, proposes likely causes and reproduction steps, and drafts the reply to the reporter. | Bug report |

## Sales & marketing

| Template | What it does | Inputs |
|---|---|---|
| **Account research + outreach** | Researches a prospect, maps pains to your product and drafts a personalised email you approve before sending. Ends with human approval. | Prospect company and contact role, What you sell |
| **Sales call prep** | Discovery questions, objection handling and a call plan tailored to the account. | Account and stage, What you know so far |
| **Campaign brief + ad variants** | Creates a campaign brief, then generates ad copy variants per channel for testing. Ends with human approval. | Product, Audience and goal |

## Researchers

| Template | What it does | Inputs |
|---|---|---|
| **Literature review assistant** | Finds and summarises sources on a question, maps agreements and gaps, and suggests research directions. | Research question |

## Teachers

| Template | What it does | Inputs |
|---|---|---|
| **Lesson plan + worksheet** | Plans a lesson with objectives, activities and differentiation, plus a worksheet with answer key. | Topic, Grade/level and duration |

## Customer support

| Template | What it does | Inputs |
|---|---|---|
| **Support ticket triage + reply** | Classifies a ticket, drafts an empathetic reply grounded in your help docs, and waits for an agent to approve. Ends with human approval. | Customer ticket, Relevant help-center text |

## Freelancers

| Template | What it does | Inputs |
|---|---|---|
| **Client proposal writer** | Turns a client brief into a scoped proposal with milestones, pricing options and assumptions. Ends with human approval. | Client brief, Your rate and availability |

## Contributing a template

Templates are declarative specs in `apps/api/isocline/services/template_library.py` (shapes: `chain`, `parallel`,
`python`). Add one, then run `pytest apps/api/tests/unit/test_template_library.py` and `make templates-check` against a
running stack. Good templates have concrete prompts, a named output format, honest limits and an approval step where
a human should decide.
