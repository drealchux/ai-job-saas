# jobs/agents.py
from langchain.agents import AgentType, initialize_agent
from langchain.tools import Tool
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate
import json
import logging
from typing import Dict, List
from .services import BrightDataScraper, JobDataParser

logger = logging.getLogger(__name__)


class JobSearchAgent:
    """
    LangChain agent that interprets natural language job queries
    and orchestrates scraping via tool calls.
    """
    
    def __init__(self, openai_api_key: str = None):
        from django.conf import settings
        self.openai_api_key = openai_api_key or settings.OPENAI_API_KEY
        self.scraper = BrightDataScraper()
        
        # Initialize LLM
        self.llm = ChatOpenAI(
            model="gpt-4",
            temperature=0.3,
            api_key=self.openai_api_key
        )
        
        # Define tools that the agent can call
        self.tools = self._build_tools()
    
    def _build_tools(self) -> List[Tool]:
        """
        Create Tool objects that the agent can invoke.
        Each tool is a callable that performs a specific action.
        """
        
        def search_linkedin(query_string: str) -> str:
            """
            Submit a LinkedIn job search request.
            Returns snapshot ID or error message.
            """
            parsed_params = self._parse_search_query(query_string)
            snapshot_id = self.scraper.search_linkedin_jobs(parsed_params)
            
            if snapshot_id:
                return json.dumps({
                    "success": True,
                    "snapshot_id": snapshot_id,
                    "source": "linkedin",
                    "params": parsed_params
                })
            else:
                return json.dumps({
                    "success": False,
                    "error": "Failed to submit LinkedIn search"
                })
        
        def search_glassdoor(query_string: str) -> str:
            """
            Submit a Glassdoor job search request.
            Returns snapshot ID or error message.
            """
            parsed_params = self._parse_search_query(query_string)
            snapshot_id = self.scraper.search_glassdoor_jobs(parsed_params)
            
            if snapshot_id:
                return json.dumps({
                    "success": True,
                    "snapshot_id": snapshot_id,
                    "source": "glassdoor",
                    "params": parsed_params
                })
            else:
                return json.dumps({
                    "success": False,
                    "error": "Failed to submit Glassdoor search"
                })
        
        return [
            Tool(
                name="search_linkedin_jobs",
                func=search_linkedin,
                description="Search for job listings on LinkedIn. Input should be a natural language query like 'ML engineer in Paris, remote'"
            ),
            Tool(
                name="search_glassdoor_jobs",
                func=search_glassdoor,
                description="Search for job listings on Glassdoor. Input should be a natural language query"
            )
        ]
    
    def run_agent(self, user_prompt: str) -> Dict:
        """
        Execute the agent with the user's natural language job query.
        
        Returns:
            {
                'intent': parsed intent,
                'extracted_params': {role, location, remote, seniority, etc.},
                'tool_calls': [
                    {'source': 'linkedin', 'snapshot_id': '...'},
                    {'source': 'glassdoor', 'snapshot_id': '...'}
                ]
            }
        """
        
        # System prompt tells the agent its role
        system_prompt = """You are a job search assistant. Your task is to:
1. Understand the user's job search query
2. Extract key parameters (role, location, seniority, remote preference, etc.)
3. Call the appropriate scraping tools (LinkedIn, Glassdoor) based on availability

When calling tools, pass the entire original query string so each tool can parse it.
Always try both LinkedIn and Glassdoor unless explicitly told otherwise.

Be concise and always extract these parameters from the query:
- role: job title or role type
- location: geographic location
- remote: true/false for remote work
- seniority: junior, mid, senior, lead, etc.
- company_type: startup, scale-up, enterprise, etc.
"""
        
        # Initialize agent
        agent = initialize_agent(
            self.tools,
            self.llm,
            agent=AgentType.CHAT_ZERO_SHOT_REACT_DESCRIPTION,
            verbose=True,
            handle_parsing_errors=True
        )
        
        try:
            # Run agent with user prompt
            result = agent.run(f"{system_prompt}\n\nUser query: {user_prompt}")
            
            # Parse the agent's response to extract tool calls and parameters
            extracted_params = self._extract_parameters(user_prompt)
            
            return {
                "success": True,
                "intent": "job_search",
                "extracted_params": extracted_params,
                "agent_response": result
            }
        
        except Exception as e:
            logger.error(f"Agent execution failed: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "extracted_params": self._extract_parameters(user_prompt)
            }
    
    def _parse_search_query(self, query: str) -> Dict:
        """
        Simple parsing of search query into parameters.
        In production, you'd make this more robust or use LLM for parsing.
        """
        query_lower = query.lower()
        
        params = {
            "role": "",
            "location": "",
            "remote": False,
            "seniority": "",
            "company_type": ""
        }
        
        # Very basic extraction (in production, use NER or proper LLM parsing)
        keywords = {
            "junior": "junior",
            "mid": "mid",
            "senior": "senior",
            "lead": "lead",
            "principal": "principal"
        }
        
        for keyword, level in keywords.items():
            if keyword in query_lower:
                params["seniority"] = level
                break
        
        # Check for remote
        if "remote" in query_lower or "work from home" in query_lower:
            params["remote"] = True
        
        # Extract role (first few words usually)
        words = query.split()
        if words:
            params["role"] = " ".join(words[:2])  # Simple heuristic
        
        return params
    
    def _extract_parameters(self, user_prompt: str) -> Dict:
        """
        Use LLM to extract structured parameters from user prompt.
        This is more reliable than regex.
        """
        extraction_prompt = PromptTemplate.from_template(
            """Extract job search parameters from this query. Return valid JSON.

Query: {query}

Return exactly this JSON structure:
{{
    "role": "job title or type",
    "location": "city or region",
    "remote": true/false,
    "seniority": "junior/mid/senior/lead",
    "company_type": "startup/scale-up/enterprise/etc or empty string",
    "keywords": "any other keywords"
}}"""
        )
        
        try:
            chain = extraction_prompt | self.llm
            result = chain.invoke({"query": user_prompt})
            
            # Parse JSON from response
            content = result.content if hasattr(result, 'content') else str(result)
            
            # Try to extract JSON from response
            try:
                params = json.loads(content)
            except json.JSONDecodeError:
                # Fallback: return basic structure
                params = {
                    "role": "",
                    "location": "",
                    "remote": False,
                    "seniority": "",
                    "company_type": ""
                }
            
            return params
        
        except Exception as e:
            logger.error(f"Parameter extraction failed: {str(e)}")
            return {
                "role": "",
                "location": "",
                "remote": False,
                "seniority": "",
                "company_type": ""
            }