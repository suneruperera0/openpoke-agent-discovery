"""Fresh holdout authored after scorer freeze. Never edit based on outcomes."""
import random
from html import escape

TASKS = [
 dict(id='named',owner='Heliotrope recovery book',project='Heliotrope',contact='Amira',duty='backup restoration',request='Ask Heliotrope recovery book to resume backup restoration.'),
 dict(id='opaque',owner='queue:806',project='Cobalt',contact='Bastien',duty='export declarations',request='Prepare the export declaration for Cobalt with Bastien.'),
 dict(id='inflection',owner='folder::83',project='Marigold',contact='Chika',duty='access policies',request='Review the Marigold access policy with Chika.'),
 dict(id='context',owner='memo B12',project='Lantern',contact='Dmitri',duty='venue bookings',request='Continue the reservation we discussed.',context='Dmitri was coordinating the Lantern venue booking.'),
 dict(id='overlap',owner='owner/006',project='Basalt',contact='Eleni',duty='audit remediation',request='Pick up Basalt audit remediation with Eleni.'),
 dict(id='contrast',owner='file.77',project='Citron',contact='Farid',duty='customs inspections',request='Contact Farid on Citron customs inspections, not accommodation invoices.'),
 dict(id='alias',owner='tracker K2',project='Larkspur',contact='Greta',duty='purchase approvals',request='Resume Larkspur procurement authorization with Greta.'),
 dict(id='semantic_gap',owner='case:940',project='Obsidian',contact='Hassan',duty='employee separations',request='Continue the Obsidian staff offboarding with Hassan.'),
 dict(id='long',owner='notes/59',project='Rill',contact='Ines',duty='expense reimbursements',request='Follow up on the Rill expense refund with Ines.',extra='Historical notes include room availability, supplier calls, meeting minutes, travel estimates, equipment counts, receipts, inspection records, delivery schedules and handover notes.'),
 dict(id='topic',owner='board:71',project='Wisteria',contact='Jules',duty='license extensions',request='Switch to Wisteria license renewals with Jules.',context='Earlier we covered Fennel equipment repairs with Kofi.',recent=True),
 dict(id='old',owner='archived/2011',project='Copperleaf',contact='Livia',duty='disability accommodations',request='Reopen Copperleaf disability accommodations with Livia.'),
 dict(id='shared',owner='register/402',project='Moraine',contact='Mateo',duty='sample shipments',request='Arrange Moraine sample shipping with Mateo.'),
 dict(id='new',owner=None,project='Yarrow',contact='Nadia',duty='sonar installation',request='Set up Yarrow sonar installation with Nadia.'),
 dict(id='ambiguous',owner=None,project='Bracken',contact='Osei',duty='visitor registration',request='Follow up with Osei.'),
]
PROJECTS=['Heliotrope','Cobalt','Marigold','Lantern','Basalt','Citron','Larkspur','Obsidian','Rill','Wisteria','Copperleaf','Moraine','Fennel']
CONTACTS=['Amira','Bastien','Chika','Dmitri','Eleni','Farid','Greta','Hassan','Ines','Jules','Kofi','Livia','Mateo']
DUTIES=['accommodation invoices','equipment repairs','visitor registration','budget reconciliation','meeting coordination','invoice disputes','customs inspections','venue bookings','access policies','sample shipments']


def fixture(task,seed):
    rng=random.Random(8400+seed)
    def history(project,contact,duty):
        return f'Responsible for {duty} on {project}; primary contact {contact}.'
    entries=[]
    if task['owner']:
        entries.append((task['owner'],history(task['project'],task['contact'],task['duty'])+' '+task.get('extra','')))
    while len(entries)<500:
        i=len(entries)
        project=task['project'] if i%4 in (0,1) else rng.choice(PROJECTS)
        contact=task['contact'] if i%4!=3 else rng.choice(CONTACTS)
        duty=rng.choice([d for d in DUTIES if d!=task['duty']])
        if i%6==0:
            project='Fennel'; duty=task['duty']
        name=f'{contact}: {project} / {duty} ({i})' if i%3 else f'dossier.{seed}.{i}'
        entries.append((name,history(project,contact,duty)))
    return entries


def transcript(task):
    return '<user_message>'+escape(task['context'])+'</user_message>' if task.get('context') else ''
