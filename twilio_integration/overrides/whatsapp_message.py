import frappe

def update_whatsapp_message_in_mc(doc, method=None):
    if doc.reference_doctype != "Multi-Channel Message":
        return

    if not doc.reference_document_name:
        return

    if not frappe.db.exists("Multi-Channel Message", doc.reference_document_name):
        return

    # Set only if not already set
    current = frappe.db.get_value(
        "Multi-Channel Message",
        doc.reference_document_name,
        "whatsapp_message"
    )

    if not current:
        frappe.db.set_value(
            "Multi-Channel Message",
            doc.reference_document_name,
            {
                "whatsapp_message": doc.name,
                "whatsapp_message_status": doc.status
            },
            update_modified=False
        )
