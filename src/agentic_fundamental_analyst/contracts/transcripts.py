from datetime import date

from pydantic import BaseModel


class TranscriptInput(BaseModel):
    accession_number: str
    filed_date: date
    exhibit_document: str  # e.g. "ex991q115earningscalltrans.htm" — the exhibit whose
    # text matched the transcript heuristic (NOT an 8-K item number: a transcript
    # exhibit lives in its own document within the accession, separate from the
    # primary 8-K's Item N.NN cover text — see data-layer.md for how this was found)
    text: str
