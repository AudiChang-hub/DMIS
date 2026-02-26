odoo.define('dms_core.dealer_columns_button', function (require) {
    "use strict";

    var ListController = require('web.ListController');

    ListController.include({
        renderButtons: function ($node) {
            this._super.apply(this, arguments);
            if (!this.$buttons) {
                return;
            }
            if (this.modelName === 'dms.dealer') {
                var self = this;
                // avoid adding twice
                if (this.$buttons.find('.o_dealer_columns_btn').length) {
                    return;
                }
                var $btn = $(
                    '<button type="button" class="btn btn-secondary o_dealer_columns_btn">欄位選擇</button>'
                );
                $btn.on('click', function () { self.onColumnsButton(); });
                // Prefer control panel buttons area, fall back to other common targets
                var $target = this.$buttons.find('.o_cp_buttons, .o_list_buttons');
                if ($target.length === 0) {
                    $target = this.$buttons.closest('.o_control_panel').find('.o_cp_buttons');
                }
                if ($target.length === 0) {
                    $target = this.$buttons;
                }
                $target.append($btn);
            }
        },
        onColumnsButton: function () {
            return this.do_action('dms_core.action_dealer_columns_wizard');
        },
    });

});
