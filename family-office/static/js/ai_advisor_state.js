/**
 * AI Advisor state module: the single owner of advisor drawer, size, conversation-panel and thread state.
 * The drawer lifecycle is an explicit state machine; an illegal transition throws instead of being ignored.
 */

(function () {
    const DRAWER_TRANSITIONS = {
        closed: ['open'],
        open: ['closing'],
        closing: ['open', 'closed'],
    };
    const PANEL_TRANSITIONS = {
        hidden: ['visible'],
        visible: ['hidden'],
    };
    const SIZES = ['default', 'half', 'full'];

    function advance(table, from, to, what) {
        if (!(table[from] || []).includes(to)) {
            throw new Error(`Illegal advisor ${what} transition: ${from} -> ${to}`);
        }
        return to;
    }

    const AdvisorState = {
        drawer: 'closed',
        size: 'default',
        panel: 'hidden',
        tab: 'section-overview',
        chatHistory: [],
        convFilter: 'all',
        conversationId: null,
        conversationTitle: 'New Conversation',
        conversationPinned: false,

        get isOpen() { return this.drawer === 'open'; },
        get isExpanded() { return this.size !== 'default'; },
        get isPanelVisible() { return this.panel === 'visible'; },

        /** Moves the drawer FSM to `target`; a request for the state it is already in is a no-op. */
        setDrawer(target) {
            if (this.drawer === target) return this.drawer;
            this.drawer = advance(DRAWER_TRANSITIONS, this.drawer, target, 'drawer');
            return this.drawer;
        },
        setPanel(target) {
            if (this.panel === target) return this.panel;
            this.panel = advance(PANEL_TRANSITIONS, this.panel, target, 'panel');
            return this.panel;
        },
        setSize(target) {
            if (!SIZES.includes(target)) throw new Error(`Unknown advisor size: ${target}`);
            this.size = target;
            return this.size;
        },
        nextSize() {
            return SIZES[(SIZES.indexOf(this.size) + 1) % SIZES.length];
        },
    };

    window.AdvisorState = AdvisorState;
})();
