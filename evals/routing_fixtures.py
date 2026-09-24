"""Fourteen authored tasks, frozen before retrieval evaluation.

Owner labels/facts are evaluator-only. Metadata sees names and prior requests.
The two demo cases are dev/explicit and dev/followup; discovery is not forced.
"""
import random

TASKS = [
    dict(split="dev", family="explicit", name="Cedar correspondence", request="Use Cedar correspondence to draft our next update.", history="Manage Project Cedar correspondence with Maya.", fact="Approved recipient: maya.ops@example.test"),
    dict(split="dev", family="followup", name="Tuesday planning", request="Draft the follow-up using our agreed recipient.", context="We discussed Project Cedar correspondence with Maya and agreed who should receive it.", history="Coordinate Project Cedar correspondence with Maya.", fact="Approved recipient: maya.ops@example.test"),
    dict(split="dev", family="paraphrase", name="Paperwork desk", request="Who can continue the supplier agreement renewal for Harbor? Draft the next step.", history="Manage Harbor supplier contract renewals and agreement deadlines.", fact="Renewal reference: HBR-731"),
    dict(split="dev", family="overlap", name="Maya / Cedar delivery", request="Follow up with Maya about the Cedar delivery, not the Birch invoice.", history="Manage Maya's Project Cedar delivery acceptance.", fact="Delivery reference: CDR-928"),
    dict(split="dev", family="old", name="Archive 2019", request="Resume the Atlas equipment warranty claim with Leo.", history="Handle Atlas equipment warranty claims with Leo.", fact="Warranty reference: AT-412"),
    dict(split="dev", family="new", name=None, request="Start tracking the Kestrel observatory telescope calibration.", history="", fact=""),
    dict(split="dev", family="ambiguous", name="Maya Cedar coordinator", request="Follow up with Maya.", history="Manage Maya's Project Cedar approvals.", fact="", alternate="Maya Birch coordinator", alternate_history="Manage Maya's Project Birch approvals."),
    dict(split="heldout", family="explicit", name="ops::Nacre/returns", request="Continue with ops::Nacre/returns and draft a status update.", history="Coordinate Nacre damaged shipment returns with Inez.", fact="Return reference: NR-603"),
    dict(split="heldout", family="followup", name="case-42", request="Prepare that follow-up with the agreed reference number.", context="We settled the return instructions for Inez's damaged Nacre shipment.", history="Coordinate Nacre damaged shipment returns with Inez.", fact="Return reference: NR-603"),
    dict(split="heldout", family="paraphrase", name="Facilities notebook", request="Continue the Sequoia building access badge replacement with Omar.", history="Track Sequoia facilities entry passes and lost badge replacements for Omar.", fact="Access desk: south entrance"),
    dict(split="heldout", family="overlap", name="support-17", request="Ask Priya about the Lumen incident review, not the Lumen invoice approval.", history="Handle Priya's Lumen incident review and remediation.", fact="Incident reference: INC-824"),
    dict(split="heldout", family="old", name="closed-notes-6", request="Pick up Noor's Solstice grant reimbursement appeal again.", history="Manage Solstice grant reimbursement appeals for Noor.", fact="Appeal reference: SOL-286"),
    dict(split="heldout", family="new", name=None, request="Coordinate the Zephyr aquarium salinity sensor installation.", history="", fact=""),
    dict(split="heldout", family="ambiguous", name="Priya incident desk", request="Send Priya a follow-up draft.", history="Coordinate Priya's Lumen incident review.", fact="", alternate="Priya procurement desk", alternate_history="Coordinate Priya's Lumen invoice approval."),
]


def fixture(task, size, seed):
    rng = random.Random(seed)
    entries = []
    if task["name"]:
        entries.append((task["name"], task["history"]))
    if task.get("alternate"):
        entries.append((task["alternate"], task["alternate_history"]))
    projects = ["Cedar", "Birch", "Harbor", "Atlas", "Nacre", "Sequoia", "Lumen", "Solstice"]
    contacts = ["Maya", "Leo", "Inez", "Omar", "Priya", "Noor"]
    duties = ["invoice approval", "travel booking", "weekly reporting", "delivery scheduling", "budget planning", "access audit"]
    while len(entries) < size:
        i = len(entries)
        p, c, d = rng.choice(projects), rng.choice(contacts), rng.choice(duties)
        entries.append((f"{p} {c} {d} #{i}", f"Coordinate {p} {d} with {c}. Track its agreed deadline and reference."))
    rng.shuffle(entries)
    return entries


def transcript(task):
    from html import escape
    return f'<user_message>{escape(task["context"])}</user_message>' if task.get("context") else ""
