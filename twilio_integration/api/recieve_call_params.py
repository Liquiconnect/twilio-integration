import frappe
from frappe.utils import cstr

@frappe.whitelist(allow_guest=True)
def twiml_say_message(msg=None, name=None):
    msg = clean_twilio_param(msg)
    name = clean_twilio_param(name)

    speak_text = f"Hello {name}. {msg}"
    speak_text = frappe.utils.escape_html(speak_text)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say>
        {speak_text}
    </Say>
    <Say>Thanks, Liquiconnect Team.</Say>
</Response>
"""

    frappe.response["content_type"] = "text/xml"
    frappe.response["response"] = xml
    return xml


def clean_twilio_param(value):
    """
    Converts:
      "b'text'" → "text"
    """
    if not value:
        return ""

    value = cstr(value)

    if value.startswith("b'") and value.endswith("'"):
        return value[2:-1]

    return value
