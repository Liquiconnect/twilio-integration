import frappe

def update_email_queue_in_mc(doc, method=None):
    if doc.reference_doctype != "Multi-Channel Message":
        return

    if not doc.reference_name:
        return

    if not frappe.db.exists("Multi-Channel Message", doc.reference_name):
        return

    # Set only if not already set
    current = frappe.db.get_value(
        "Multi-Channel Message",
        doc.reference_name,
        "email_queue"
    )

    if not current:
        frappe.db.set_value(
            "Multi-Channel Message",
            doc.reference_name,
            {
                "email_queue": doc.name,
                "email_status": doc.status
            },
            update_modified=False
        )
