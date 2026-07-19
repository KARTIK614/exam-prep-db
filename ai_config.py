"""Static AI/notes configuration — filename maps for Gemini context lookup."""
import os
from config import Config

NOTES_DIR = Config.NOTES_DIR

NOTES_FILES = {
    'History': [
        'rajasthan-history-culture-notes.md',
        'exam-quick-revision-notes.md',
        'syllabus-analysis.md',
    ],
    'Geography': [
        'rajasthan-geography-notes.md',
        'exam-quick-revision-notes.md',
        'syllabus-analysis.md',
    ],
    'Polity': [
        'rajasthan-studies-notes.md',
        'exam-quick-revision-notes.md',
    ],
    'CS': [
        'computer-anudeshak-2022-paper1-solutions.md',
        'yct-computer-anudeshak-practice-sets.md',
        'syllabus-analysis.md',
    ],
    'Science': [
        'police-constable-2022-paper-solutions.md',
        'exam-quick-revision-notes.md',
    ],
    'Current': ['exam-quick-revision-notes.md', 'syllabus-analysis.md'],
    'Reasoning': ['exam-quick-revision-notes.md'],
    'Quant': ['exam-quick-revision-notes.md'],
}

SUPPLEMENTARY_FILES = [
    'rssb-exam-answer-keys-compilation.md',
    'syllabus-analysis.md',
]

# NOTE: `GEMINI_CLI` used to point at a Node.js CLI binary. As of the REST
# migration (see ai_utils.call_gemini) we hit Google's HTTPS endpoint directly
# using `GEMINI_API_KEY`, so no binary is required. Kept only as a comment for
# grep-ability; delete after a release cycle.
