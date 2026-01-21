# Copyright (c) 2026, lnder_fintech and contributors
# For license information, please see license.txt

import json
from urllib.parse import parse_qs

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class TwilioCallLog(Document):
	def before_insert(self):
		if not self.timestamp:
			self.timestamp = now_datetime()

		try:
			set_call_data(self)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Twilio Call Log: before_insert failed")


def _get_value(data, key):
	"""
	Twilio form data -> list
	Twilio JSON -> string
	This normalizes both.
	"""
	value = data.get(key)
	if isinstance(value, list):
		return value[0]
	return value


def set_call_data(doc):
	if not doc.response:
		return

	response_dict = json.loads(doc.response)

	call_sid = _get_value(response_dict, "CallSid")
	from_no = _get_value(response_dict, "From")
	to_no = _get_value(response_dict, "To")
	call_status = _get_value(response_dict, "CallStatus")
	duration = _get_value(response_dict, "Duration")

	if call_sid and not doc.call_sid:
		doc.call_sid = call_sid

	if from_no and not doc.from_no:
		doc.from_no = from_no

	if to_no and not doc.to_no:
		doc.to_no = to_no

	if call_status and not doc.call_status:
		doc.call_status = call_status

	if duration and not doc.duration:
		doc.duration = int(duration)

	if not call_sid:
		return

	call_log = frappe.db.exists("Twilio Call Log", {"call_sid": call_sid, "type": "Call"})

	if not call_log:
		return

	current = frappe.db.get_value("Twilio Call Log", call_log, "call_back_recieved")

	if not current:
		frappe.db.set_value("Twilio Call Log", call_log, "call_back_recieved", 1)


@frappe.whitelist(allow_guest=True)
def twilio_call_log_endpoint():
	raw_data = frappe.request.get_data(as_text=True)
	content_type = frappe.request.headers.get("Content-Type", "")

	if not raw_data or not raw_data.strip():
		frappe.log_error("Empty request body", "Twilio Call Log Webhook")

	try:
		if "application/json" in content_type:
			payload = json.loads(raw_data)
		else:
			payload = parse_qs(raw_data)

		new_doc = frappe.get_doc(
			{
				"doctype": "Twilio Call Log",
				"type": "Callback",
				"response": json.dumps(payload, indent=4),
			}
		)
		new_doc.insert(ignore_permissions=True)
		return json.dumps({"name": new_doc.name, "status": "Success", "status_code": 200})

	except json.JSONDecodeError:
		frappe.log_error(raw_data, "Twilio Call Log: Invalid JSON")

		frappe.get_doc(
			{
				"doctype": "Twilio Call Log",
				"response": raw_data,
			}
		).insert(ignore_permissions=True)

	except Exception:
		frappe.log_error(frappe.get_traceback(), "Twilio Call Log: Webhook Failure")
		frappe.throw("Failed to process Twilio webhook")
	finally:
		frappe.db.commit()



@frappe.whitelist()
def make_twilio_call():
    pass