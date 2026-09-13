"""Metadata only: identifiers do not alter transmitted prompt bytes."""
PROMPT_VERSIONS = {purpose: "pre-stage5-v1" for purpose in
                   ("chat", "extraction", "router", "title", "summary", "diagnosis", "web_tools")}
