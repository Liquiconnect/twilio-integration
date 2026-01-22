# Copyright (c) 2026, lnder_fintech
# License: see license.txt

import json
from urllib.parse import parse_qs

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime
from twilio.rest import Client


# -------------------------------------------------------------------
# DocType Logic
# -------------------------------------------------------------------

class TwilioCallLog(Document):
	def before_insert(self):
		if not self.timestamp:
			self.timestamp = now_datetime()

		try:
			set_call_data(self)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				"Twilio Call Log: before_insert failed"
			)


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def _get_value(data, key):
	value = data.get(key)
	if isinstance(value, list):
		return value[0]
	return value


def set_call_data(doc):
	if not doc.response:
		return

	data = json.loads(doc.response)

	call_sid = _get_value(data, "CallSid")
	call_status = _get_value(data, "CallStatus")
	duration = _get_value(data, "Duration")
	from_no = _get_value(data, "From")
	to_no = _get_value(data, "To")

	if call_sid and not doc.call_sid:
		doc.call_sid = call_sid

	if call_status:
		doc.call_status = call_status

	if duration:
		try:
			doc.duration = int(duration)
		except ValueError:
			pass

	if from_no:
		doc.from_no = from_no

	if to_no:
		doc.to_no = to_no

	if not call_sid:
		return

	parent = frappe.db.exists(
		"Twilio Call Log",
		{"call_sid": call_sid, "type": "Call"}
	)

	if parent:
		frappe.db.set_value(
			"Twilio Call Log",
			parent,
			"call_back_recieved",
			1
		)


# -------------------------------------------------------------------
# Generic Call Initiator
# -------------------------------------------------------------------

@frappe.whitelist()
def initiate_twilio_call(
	to_number,
	twiml_url,
	purpose,
	reference_doctype=None,
	reference_name=None,
	meta=None
):
	"""
	Single entry point for ALL outgoing calls.
	Creates log first, then calls Twilio, then updates SID.
	"""

	if "twilio_integration" not in frappe.get_installed_apps():
		frappe.throw("Twilio integration not installed")

	from twilio_integration.twilio_integration.twilio_handler import Twilio

	twilio = Twilio.connect()
	if not twilio:
		frappe.throw("Twilio not configured")

	account_sid = twilio.account_sid
	auth_token = twilio.settings.get_password("auth_token")
	from_number = twilio.settings.whatsapp_no

	log = frappe.get_doc(
		{
			"doctype": "Twilio Call Log",
			"type": "Call",
			"purpose": purpose,
			"to_no": to_number,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"meta": json.dumps(meta or {}),
			"call_status": "initiated",
		}
	)
	log.insert(ignore_permissions=True)

	client = Client(account_sid, auth_token)

	try:
		call = client.calls.create(
			to=to_number,
			from_=from_number,
			url=twiml_url,
			record=False,
		)

		frappe.db.set_value(
			"Twilio Call Log",
			log.name,
			{
				"call_sid": call.sid,
				"call_status": "queued",
			},
		)

	except Exception:
		frappe.db.set_value(
			"Twilio Call Log",
			log.name,
			"call_status",
			"failed",
		)
		frappe.log_error(
			frappe.get_traceback(),
			"Twilio Call Initiation Failed"
		)
		raise

	return {
		"log": log.name,
		"call_sid": call.sid,
		"status": "queued",
	}


# -------------------------------------------------------------------
# Callback Webhook
# -------------------------------------------------------------------

@frappe.whitelist(allow_guest=True)
def twilio_call_log_endpoint():
	raw_data = frappe.request.get_data(as_text=True)
	content_type = frappe.request.headers.get("Content-Type", "")

	if not raw_data:
		return

	try:
		if "application/json" in content_type:
			payload = json.loads(raw_data)
		else:
			payload = parse_qs(raw_data)

		doc = frappe.get_doc(
			{
				"doctype": "Twilio Call Log",
				"type": "Callback",
				"response": json.dumps(payload),
			}
		)
		doc.insert(ignore_permissions=True)

	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			"Twilio Callback Failure"
		)
		frappe.throw("Webhook processing failed")

	finally:
		frappe.db.commit()
