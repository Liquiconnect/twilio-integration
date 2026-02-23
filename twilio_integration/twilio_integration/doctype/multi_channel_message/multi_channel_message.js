frappe.ui.form.on("Multi-Channel Message", {
	refresh(frm) {
		frm.set_query("sender", () => {
			return {
				filters: {
					enable_outgoing: 1,
				},
			};
		});

		// Toggle Actions button visibility
		frm.trigger("toggle_actions_button");
	},
	whatsapp_template(frm) {
		generate_variables(frm);
	},

	toggle_actions_button(frm) {
		if (frm.doc.workflow_state === "Draft") {
			// Show Actions button
			frm.page.actions_btn_group.show();
		} else {
			// Hide Actions button
			frm.page.actions_btn_group.hide();
		}
	},
});

function generate_variables(frm) {
	let content = frm.doc.sample_data;

	if (!content) {
		frm.clear_table("template_details");
		frm.refresh_field("template_details");
		return;
	}

	// Extract {{number}} patterns
	let matches = content.match(/\{\{\d+\}\}/g);

	if (!matches) {
		frm.clear_table("template_details");
		frm.refresh_field("template_details");
		return;
	}

	// Remove duplicates
	let unique_vars = [...new Set(matches)];

	// Clear existing rows
	frm.clear_table("template_details");

	// Add rows
	unique_vars.forEach((variable) => {
		let row = frm.add_child("template_details");
		row.variable = variable;
		row.value = "";
	});

	frm.refresh_field("template_details");
}
