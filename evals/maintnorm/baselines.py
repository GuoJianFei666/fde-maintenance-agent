"""Published MaintNorm Table 7 numbers.

Copied from Bikaun, Hodkiewicz, and Liu (2024), Table 7, and checked against
nlp-tlp/maintnorm RESULTS.md at commit e98ca406f7afffbb0ab3243aa7c922f3b64bc7c8.
Values are the published percentages. This module does not contain results
from this repository's model.
"""

CITATION = {
    "paper": "Bikaun, Tyler, Melinda Hodkiewicz, and Wei Liu. 2024. MaintNorm: A corpus and benchmark model for lexical normalisation and masking of industrial maintenance short text. Proceedings of the Ninth Workshop on Noisy and User-generated Text (W-NUT 2024), pages 68-78.",
    "url": "https://aclanthology.org/2024.wnut-1.7/",
    "table": "Table 7",
    "repo": "https://github.com/nlp-tlp/maintnorm/blob/e98ca406f7afffbb0ab3243aa7c922f3b64bc7c8/RESULTS.md",
    "unit": "percent",
}

# Rows: company, extra training data, then precision, recall, E.R.R.
TABLE_7 = {
    "MaintNorm": [
        ("A", "N", 99.9, 95.8, 95.2),
        ("A", "Y", 99.9, 98.1, 96.6),
        ("B", "N", 98.9, 94.6, 90.0),
        ("B", "Y", 99.7, 98.1, 96.6),
        ("C", "N", 99.4, 95.2, 89.1),
        ("C", "Y", 99.5, 96.8, 92.4),
        ("A+B+C", "-", 99.7, 97.5, 95.8),
    ],
    "LAI": [
        ("A", "N", 0, 0, 0),
        ("A", "Y", 0, 0, 0),
        ("B", "N", 0, 0, 0),
        ("B", "Y", 0, 0, 0),
        ("C", "N", 0, 0, 0),
        ("C", "Y", 0, 0, 0),
        ("A+B+C", "-", 0, 0, 0),
    ],
    "MFR": [
        ("A", "N", 99.9, 91.7, 90.9),
        ("A", "Y", 99.9, 91.7, 90.9),
        ("B", "N", 99.8, 93.9, 90.2),
        ("B", "Y", 99.8, 93.9, 90.2),
        ("C", "N", 99.5, 89.9, 78.6),
        ("C", "Y", 99.5, 89.9, 78.6),
        ("A+B+C", "-", 99.8, 93.0, 89.4),
    ],
    "UFAL": [
        ("A", "N", 99.8, 92.0, 91.0),
        ("A", "Y", 99.9, 92.1, 91.3),
        ("B", "N", 99.6, 91.0, 85.5),
        ("B", "Y", 99.6, 91.7, 86.5),
        ("C", "N", 99.4, 86.6, 71.9),
        ("C", "Y", 99.1, 86.6, 71.5),
        ("A+B+C", "-", 99.5, 90.2, 85.0),
    ],
}

OURS = ("待运行", "待运行", "待运行")
