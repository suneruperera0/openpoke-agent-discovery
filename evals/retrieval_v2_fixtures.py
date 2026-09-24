"""New development tasks only. No v2 holdout has been authored or evaluated."""
import random
from html import escape

# Each owner has task evidence in real-style instruction history. Labels stay in
# the evaluator. Distractor histories use the same templates as target histories.
TASKS = [
 dict(id='exact', owner='Vega dispatch desk', project='Vega', contact='Rosa', duty='freight damage claims', request='Use Vega dispatch desk to continue the freight claim.'),
 dict(id='opaque', owner='ticket-81', project='Pollen', contact='Tariq', duty='certificate renewals', request='Continue the certificate renewal for Pollen with Tariq.'),
 dict(id='plural', owner='notebook 204', project='Mistral', contact='Ada', duty='warranty extensions', request='Prepare the Mistral warranty extension with Ada.'),
 dict(id='context', owner='desk/41', project='Ember', contact='Luis', duty='permit appeals', request='Continue that appeal.', context='We discussed the Ember permit with Luis.'),
 dict(id='overlap', owner='workstream-9', project='Delta', contact='Zara', duty='incident retrospectives', request='Continue the Delta incident retrospective with Zara.'),
 dict(id='excluded', owner='ledger-7', project='Boreal', contact='Hugo', duty='shipment inspections', request='Follow up with Hugo about Boreal shipment inspections, not invoice approvals.'),
 dict(id='paraphrase', owner='file-Q', project='Aster', contact='Nina', duty='supplier contract renewals', request='Pick up Aster vendor agreement extensions with Nina.'),
 dict(id='old', owner='archive/2008', project='Reef', contact='Otto', duty='insurance reimbursements', request='Resume the Reef insurance reimbursement with Otto.'),
 dict(id='long_history', owner='operations/6', project='Comet', contact='Esme', duty='equipment reservations', request='Continue Comet equipment reservations with Esme.', extra='The records also mention packing lists, delivery timing, inspection reports, older payments and contact details.'),
 dict(id='topic_switch', owner='case-Z', project='Sable', contact='Arun', duty='security reviews', request='Now work on Sable security reviews with Arun.', context='Earlier we discussed transport scheduling for Finch with Cleo.', recent=True),
 dict(id='number_ref', owner='record_732', project='Opal', contact='Leila', duty='laboratory calibrations', request='Continue Opal calibration record 732 with Leila.'),
 dict(id='shared_person', owner='planning-54', project='Tundra', contact='Felix', duty='training registrations', request='Resume Tundra training registrations for Felix.'),
 dict(id='new', owner=None, project='Helix', contact='Daria', duty='underwater sensor installations', request='Start the Helix underwater sensor installation with Daria.'),
 dict(id='ambiguous', owner=None, project='Vale', contact='Bruno', duty='travel approvals', request='Follow up with Bruno.', ambiguous=True),
]
PROJECTS = ['Vega','Pollen','Mistral','Ember','Delta','Boreal','Aster','Reef','Comet','Sable','Opal','Tundra','Finch']
CONTACTS = ['Rosa','Tariq','Ada','Luis','Zara','Hugo','Nina','Otto','Esme','Arun','Leila','Felix','Cleo']
DUTIES = ['invoice approvals','transport scheduling','supplier onboarding','travel approvals','security reviews','shipment inspections','equipment reservations','training registrations','permit appeals','certificate renewals']


def instruction(project, contact, duty):
    return f'Manage {project} {duty} with {contact}.'


def fixture(task, seed):
    """Generate one nested 500-record pool. Shuffle each size separately."""
    rng = random.Random(seed)
    entries = []
    if task['owner']:
        history = instruction(task['project'],task['contact'],task['duty'])
        entries.append((task['owner'], history + ' ' + task.get('extra','')))
    for i in range(500 - len(entries)):
        # Structured hard negatives followed by mixed distractors, available at
        # all scales; names and histories are both informative or both opaque.
        project = task['project'] if i % 3 == 0 else rng.choice(PROJECTS)
        contact = task['contact'] if i % 3 != 2 else rng.choice(CONTACTS)
        duty = rng.choice([d for d in DUTIES if d != task['duty']])
        if i % 7 == 0:
            duty = task['duty']; project = 'Finch' if task['project'] != 'Finch' else 'Reef'
        name = f'{project} {contact} {duty} / {i}' if i % 2 == 0 else f'work-item-{seed}-{i}'
        entries.append((name, instruction(project, contact, duty)))
    return entries


def transcript(task):
    return '<user_message>' + escape(task['context']) + '</user_message>' if task.get('context') else ''
