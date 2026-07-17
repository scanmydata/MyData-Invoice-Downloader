"""Αντιστοίχιση επικεφαλίδων -> πεδία.

ΚΡΙΣΙΜΟ: το ταίριασμα είναι **whole-string**, ποτέ substring.

Το e3_brain.py:1170 κάνει substring match, και το alias «subscription key»
περιέχεται στο «Subscription key e-timologio» (στήλη BL). Έτσι θα άρπαζε το
κλειδί του e-timologio και θα το έστελνε ως myDATA key -> 403 σε κάθε πελάτη.
Τα δύο προϊόντα έχουν διαφορετικά κλειδιά:

    BI = «Api myData»                  <- ΑΥΤΟ θέλουμε (REST API)
    BL = «Subscription key e-timologio» <- ΑΛΛΟ προϊόν

Οι 42 από τους 153 πελάτες που έχουν BL αλλά όχι BI είναι ακριβώς η παγίδα.
"""

from __future__ import annotations

from ..normalize import norm_header

#: πεδίο -> κανονικοποιημένες επικεφαλίδες που το ορίζουν
FIELD_ALIASES: dict[str, set[str]] = {
    "afm": {"αφμ", "α φ μ", "afm", "vat", "vat number", "αφμ υποχρεου"},
    "name": {
        "επωνυμια επωνυμο",
        "επωνυμια",
        "επωνυμο",
        "ονομασια",
        "name",
    },
    "first_name": {"ονομα", "first name"},
    "mydata_user": {
        "ονομα χρηστη mydata",
        "ονομα χρηστη my data",
        "aade user id",
        "aade user",
        "χρηστης mydata",
    },
    "mydata_key": {
        "api mydata",
        "api my data",
        "ocp apim subscription key",
        "subscription key mydata",
        "κλειδι api mydata",
    },
}

#: Επικεφαλίδες που μοιάζουν σχετικές αλλά ΔΕΝ πρέπει ποτέ να διαβαστούν ως
#: myDATA credentials. Τις ονομάζουμε ρητά ώστε μια μελλοντική προσθήκη alias
#: να μη μπορεί να τις αρπάξει σιωπηλά.
NEVER_MYDATA: dict[str, str] = {
    "subscription key e timologio": "κλειδί e-timologio (άλλο προϊόν)",
    "ονομα χρηστη e timologio": "χρήστης e-timologio (άλλο προϊόν)",
    "συνθηματικο e timologio": "συνθηματικό e-timologio (άλλο προϊόν)",
    "συνθηματικο mydata": "συνθηματικό web myDATA, όχι το API key",
}

_LOOKUP: dict[str, str] = {}
for _field, _headers in FIELD_ALIASES.items():
    for _header in _headers:
        _LOOKUP[_header] = _field


def field_for(header: object) -> str | None:
    """Επιστρέφει το πεδίο για μια επικεφαλίδα, ή None.

    Whole-string μόνο. Ό,τι είναι στο NEVER_MYDATA επιστρέφει ρητά None.
    """
    key = norm_header(header)
    if not key or key in NEVER_MYDATA:
        return None
    return _LOOKUP.get(key)
