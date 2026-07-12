"""Static AI/notes configuration — filename maps for Gemini context lookup."""
import os
import shutil
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

GEMINI_CLI = Config.GEMINI_CLI or shutil.which('gemini') or os.path.expanduser('~/.nvm/versions/node/v20.20.2/bin/gemini')
