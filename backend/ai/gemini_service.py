import google.generativeai as genai
from config import settings


class GeminiService:
    def __init__(self):
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self.model = genai.GenerativeModel("gemini-3.1-flash-lite-preview")

    def _generate(self, prompt: str) -> str:
        response = self.model.generate_content(prompt)
        return response.text

    def generate_employee_bio(self, name: str, designation: str, department: str, skills: str) -> str:
        prompt = (
            f"Write a professional bio (3-4 sentences) for an employee:\n"
            f"Name: {name}\nDesignation: {designation}\n"
            f"Department: {department}\nSkills: {skills}\n"
            f"Make it professional and suitable for a company intranet profile."
        )
        return self._generate(prompt)

    def detect_duplicate_profiles(self, employees_data: str) -> str:
        prompt = (
            f"Analyze the following employee data and identify:\n"
            f"1. Potential duplicate profiles (similar names/emails)\n"
            f"2. Incomplete profiles (missing critical fields)\n"
            f"Return a JSON with 'duplicates' and 'incomplete' arrays.\n\n"
            f"Employee Data:\n{employees_data}"
        )
        return self._generate(prompt)

    def score_resume(self, resume_text: str, job_description: str) -> str:
        prompt = (
            f"Score this resume against the job description on a scale of 0-100.\n"
            f"Provide a breakdown of:\n"
            f"- Skills Match (0-30)\n- Experience Relevance (0-30)\n"
            f"- Education Fit (0-20)\n- Overall Impression (0-20)\n\n"
            f"Job Description:\n{job_description}\n\n"
            f"Resume:\n{resume_text}\n\n"
            f"Return a JSON with 'total_score', 'skills_match', 'experience_relevance', "
            f"'education_fit', 'overall_impression', and 'summary' fields."
        )
        return self._generate(prompt)

    def generate_interview_questions(self, job_description: str, resume_text: str, num_questions: int = 10) -> str:
        prompt = (
            f"Generate {num_questions} interview questions for a candidate.\n"
            f"Base questions on the job requirements and the candidate's resume.\n"
            f"Include a mix of technical, behavioral, and situational questions.\n\n"
            f"Job Description:\n{job_description}\n\n"
            f"Resume:\n{resume_text}\n\n"
            f"Return a JSON array of objects with 'question', 'type' (technical/behavioral/situational), "
            f"and 'focus_area' fields."
        )
        return self._generate(prompt)

    def compare_candidates(self, candidates_data: str, job_description: str) -> str:
        prompt = (
            f"Compare these shortlisted candidates for the following job:\n\n"
            f"Job Description:\n{job_description}\n\n"
            f"Candidates:\n{candidates_data}\n\n"
            f"Provide a side-by-side comparison with strengths, weaknesses, and a ranking. "
            f"Return as JSON with 'comparison' array and 'recommendation' field."
        )
        return self._generate(prompt)

    def analyze_leave_patterns(self, leave_data: str) -> str:
        prompt = (
            f"Analyze these leave patterns and provide insights:\n\n"
            f"{leave_data}\n\n"
            f"Identify:\n1. Frequent leave-takers\n2. Peak leave periods\n"
            f"3. Department-wise patterns\n4. Any concerning trends\n"
            f"Return a JSON with 'insights', 'peak_periods', 'department_patterns', and 'recommendations'."
        )
        return self._generate(prompt)

    def predict_team_capacity(self, attendance_data: str, leave_data: str) -> str:
        prompt = (
            f"Based on historical attendance and upcoming leave data, predict team capacity.\n\n"
            f"Attendance History:\n{attendance_data}\n\n"
            f"Upcoming Leaves:\n{leave_data}\n\n"
            f"Predict capacity for the next 2 weeks by department. "
            f"Return a JSON with 'predictions' array containing date, department, "
            f"available_count, and capacity_percentage."
        )
        return self._generate(prompt)

    def generate_review_summary(self, review_data: str) -> str:
        prompt = (
            f"Generate a comprehensive performance review summary based on:\n\n"
            f"{review_data}\n\n"
            f"Include:\n1. Key achievements\n2. Areas for improvement\n"
            f"3. Goal recommendations\n4. Overall assessment\n"
            f"Return a well-structured summary suitable for HR records."
        )
        return self._generate(prompt)

    def answer_policy_question(self, question: str, policy_context: str) -> str:
        prompt = (
            f"You are an HR assistant for HireFlow AI. Answer the employee's question "
            f"based on the company policy documents provided.\n\n"
            f"Policy Context:\n{policy_context}\n\n"
            f"Employee Question: {question}\n\n"
            f"Provide a clear, helpful, and concise answer. If the information is not "
            f"available in the policies, say so and suggest who to contact."
        )
        return self._generate(prompt)

    def generate_hr_summary(self, analytics_data: str) -> str:
        prompt = (
            f"Generate a monthly HR summary report based on this data:\n\n"
            f"{analytics_data}\n\n"
            f"Include sections on:\n1. Headcount Overview\n2. Hiring & Attrition\n"
            f"3. Leave Utilization\n4. Performance Highlights\n"
            f"5. Key Recommendations\n"
            f"Make it professional and actionable."
        )
        return self._generate(prompt)

    def generate_offer_letter(self, employee_name: str, designation: str, department: str,
                               salary: float, joining_date: str, company_name: str = "HireFlow AI") -> str:
        prompt = (
            f"Generate a professional offer letter with the following details:\n"
            f"Company: {company_name}\n"
            f"Candidate Name: {employee_name}\n"
            f"Designation: {designation}\n"
            f"Department: {department}\n"
            f"Annual CTC: {salary}\n"
            f"Joining Date: {joining_date}\n\n"
            f"Include standard clauses for probation, benefits, and terms. "
            f"Make it formal and professional."
        )
        return self._generate(prompt)
