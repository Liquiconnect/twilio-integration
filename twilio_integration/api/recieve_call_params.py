import frappe

@frappe.whitelist(allow_guest=True)
def twiml_say_message(msg=None, name=None):
    from frappe.utils.response import build_response

    msg = frappe.utils.cstr(msg)
    name = frappe.utils.cstr(name)

    speak_text = f"Hello {name}. {msg}" if name else msg

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice" language="en-IN">
        {speak_text}
    </Say>
</Response>
"""
    frappe.local.response.http_status_code = 200
    frappe.local.response.headers["Content-Type"] = "text/xml"
    frappe.local.response.response = xml
