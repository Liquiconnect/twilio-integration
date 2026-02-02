import frappe

def after_migrate():
    create_multichannelmessage_workflow()

def create_multichannelmessage_workflow():
    workflow_name = "Multi-Channel Message Workflow"
    doctype = "Multi-Channel Message"

    # --- Define states and their styles ---
    states = {
        "Draft": "Primary",
        "Approved": "Success",
        "Sent": "Success",
        "Queue": "Info",
        "Error": "Danger"
    }

    # --- Define workflow actions ---
    actions = ["Approve", "Send Alert", "Retry", "Fail"]

    # --- Create Workflow States if missing ---
    for state, style in states.items():
        if not frappe.db.exists("Workflow State", state):
            frappe.get_doc({
                "doctype": "Workflow State",
                "workflow_state_name": state,
                "style": style
            }).insert(ignore_permissions=True)

    # --- Create Workflow Actions if missing ---
    for action in actions:
        if not frappe.db.exists("Workflow Action Master", action):
            frappe.get_doc({
                "doctype": "Workflow Action Master",
                "workflow_action_name": action
            }).insert(ignore_permissions=True)

    # --- Create the Workflow if it does not exist ---
    if not frappe.db.exists("Workflow", workflow_name):
        workflow = frappe.get_doc({
            "doctype": "Workflow",
            "workflow_name": workflow_name,
            "document_type": doctype,
            "is_active": 1,
            "workflow_state_field": "workflow_state",
            "states": [
                {"state": "Draft", "allow_edit": "System Manager", "doc_status": 0},
                {"state": "Approved", "allow_edit": "System Manager", "doc_status": 1},
                {"state": "Sent", "allow_edit": "System Manager", "doc_status": 1},
                {"state": "Queue", "allow_edit": "System Manager", "doc_status": 0},
                {"state": "Error", "allow_edit": "System Manager", "doc_status": 2},
            ],
            "transitions": [
                {"state": "Draft", "action": "Approve", "next_state": "Approved", "allowed": "System Manager", "allow_self_approval": 1},
                {"state": "Approved", "action": "Send Alert", "next_state": "Queue", "allowed": "System Manager", "allow_self_approval": 1},
                {"state": "Queue", "action": "Retry", "next_state": "Sent", "allowed": "System Manager", "allow_self_approval": 1},
                {"state": "Queue", "action": "Fail", "next_state": "Error", "allowed": "System Manager", "allow_self_approval": 1},
            ]
        })
        workflow.insert(ignore_permissions=True)
        frappe.db.commit()


