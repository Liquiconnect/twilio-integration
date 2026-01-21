import frappe


def execute():
	create_whatsapp_template_reference()


def create_template(template_name, message):
	doctype = "WhatsApp Template Reference"
	existing = frappe.db.exists(doctype, template_name)
	if existing:
		doc = frappe.get_doc(doctype, template_name)
		doc.reference_message_template = message
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc(
			{
				"doctype": doctype,
				"template_name": template_name,
				"reference_message_template": message,
			}
		)
		doc.insert(ignore_permissions=True)
	frappe.db.commit()


def create_whatsapp_template_reference():
	if "twilio_integration" in frappe.get_installed_apps():
		template_data = {
			"send_mc_alert_without_attachment": {
				"reference_message_template": """Dear {{1}},

{{2}}

Best regards,
Liquiconnect Team
""",
				"reference_message_template_helper": """
{{1}} → Recipients Name
{{2}} → Message Content
""",
			},
			"copy_send_mc_alert_with_attachment": {
				"reference_message_template": """Dear {{1}},

{{2}}

Best regards,
Liquiconnect Team

{{3}}
""",
				"reference_message_template_helper": """
{{1}} → Recipients Name
{{2}} → Message Content
{{3}} → Media URL
""",
			},
		}

		for doc_name, values in template_data.items():
			if frappe.db.exists("WhatsApp Template Reference", doc_name):
				doc = frappe.get_doc("WhatsApp Template Reference", doc_name)
			else:
				doc = frappe.new_doc("WhatsApp Template Reference")
				doc.template_name = doc_name

			doc.reference_message_template = values["reference_message_template"]
			doc.reference_message_template_helper = values.get(
				"reference_message_template_helper", ""
			)
			doc.save(ignore_permissions=True)
