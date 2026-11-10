"""Builds the MOM PDF in the company layout: header table, attendees, purpose,
key outcomes, discussion by item, action items. Pure Python (fpdf2), no AWS calls."""
from fpdf import FPDF
from fpdf.fonts import FontFace

NAVY = (31, 56, 100)
LIGHT = (221, 230, 243)
GREY = (90, 90, 90)
TBC = "To be confirmed"

_REPLACEMENTS = {
    "–": "-", "—": "-", "‘": "'", "’": "'", "“": '"', "”": '"',
    "•": "-", "…": "...", " ": " ",
}


def _t(value, default=""):
    """Core PDF fonts are latin-1 only: map common punctuation, replace the rest."""
    text = default if value is None or value == "" else str(value)
    for old, new in _REPLACEMENTS.items():
        text = text.replace(old, new)
    return text.encode("latin-1", "replace").decode("latin-1")


class _MomPdf(FPDF):
    def __init__(self, footer_title):
        super().__init__(format="A4")
        self.footer_title = _t(footer_title)
        self.set_margins(15, 15, 15)
        self.set_auto_page_break(auto=True, margin=18)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*GREY)
        self.cell(0, 6, f"MoM - {self.footer_title} - Page {self.page_no()}", align="C")


def _heading(pdf, text):
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 8, _t(text), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 10)


def _table(pdf, headings, rows, widths):
    head = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=NAVY)
    with pdf.table(col_widths=widths, headings_style=head, line_height=5,
                   text_align="LEFT", padding=1.5) as table:
        header = table.row()
        for h in headings:
            header.cell(_t(h))
        for r in rows:
            row = table.row()
            for cell in r:
                row.cell(_t(cell))


def build_pdf(mom):
    title = mom.get("title") or "Meeting"
    pdf = _MomPdf(title)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 10, "MINUTES OF MEETING", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(*GREY)
    pdf.cell(0, 7, _t(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*NAVY)
    pdf.set_line_width(0.6)
    pdf.line(15, pdf.get_y() + 1, 195, pdf.get_y() + 1)
    pdf.set_line_width(0.2)  # thin, light borders for the tables
    pdf.set_draw_color(170, 180, 195)
    pdf.ln(5)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 10)

    # document control / header table
    meta = [
        ("Date / time", mom.get("meeting_date")),
        ("Mode", mom.get("mode")),
        ("Client", mom.get("client")),
        ("Prepared by", mom.get("prepared_by")),
    ]
    label = FontFace(emphasis="BOLD", fill_color=LIGHT)
    with pdf.table(col_widths=(40, 140), first_row_as_headings=False, line_height=5, padding=1.5) as table:
        for name, value in meta:
            row = table.row()
            row.cell(name, style=label)
            row.cell(_t(value, TBC))

    _heading(pdf, "1. Attendees")
    groups = {}
    for a in mom.get("attendees", []):
        groups.setdefault(a.get("group") or "Not stated", []).append(a["name"])
    rows = [(g, ", ".join(names)) for g, names in groups.items()] or [("Not stated", "No names heard in the recording")]
    rows.append(("To be added", "Attendance is not captured by this tool. Confirm and add the full attendee list."))
    _table(pdf, ("Group", "Participants"), rows, (45, 135))
    pdf.set_font("Helvetica", "I", 8)
    pdf.cell(0, 5, "Names above are only people who spoke or were named in the recording; affiliations only if stated.",
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)

    _heading(pdf, "2. Purpose")
    pdf.multi_cell(0, 5, _t(mom.get("purpose") or mom.get("summary"), TBC), new_x="LMARGIN", new_y="NEXT")

    _heading(pdf, "3. Key outcomes")
    outcomes = mom.get("decisions") or ["No decisions recorded."]
    for o in outcomes:
        pdf.set_x(18)
        pdf.multi_cell(0, 5, "-  " + _t(o), new_x="LMARGIN", new_y="NEXT")

    _heading(pdf, "4. Discussion by item")
    items = mom.get("discussion_items") or []
    rows = [(f"{i}. {d['item']}", d["discussion"], d.get("status") or "-") for i, d in enumerate(items, 1)]
    _table(pdf, ("Item", "Discussion", "Decision / status"), rows or [("-", mom.get("summary", ""), "-")], (40, 100, 40))

    _heading(pdf, "5. Action items")
    rows = [
        (str(i), a["task"], a["owner"] or "Unassigned (no owner stated)", a["due_date"] or "No date stated")
        for i, a in enumerate(mom.get("action_items", []), 1)
    ]
    _table(pdf, ("#", "Action", "Owner", "Due"), rows or [("-", "No action items", "-", "-")], (10, 90, 45, 35))

    pdf.ln(3)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(*GREY)
    pdf.multi_cell(0, 4, "Generated automatically from a meeting recording. Review for accuracy before sharing.",
                   new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
