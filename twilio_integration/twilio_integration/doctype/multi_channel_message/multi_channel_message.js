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
