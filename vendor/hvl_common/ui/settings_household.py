"""
Shared Household Members, Magic Invites & Access Control Groups UI (hvl_common.ui.settings_household).
Provides canonical SSR HTML helpers for managing household members, magic invite links,
and custom access control groups across HVL applications.
"""

from __future__ import annotations

from typing import Any, Iterable
from markupsafe import Markup, escape


def hvl_household_members_section(
    members: Iterable[dict[str, Any]],
    current_member: dict[str, Any] | None = None,
    *,
    invites: Iterable[dict[str, Any]] | None = None,
    is_local_mode: bool = False,
) -> Markup:
    """Emit canonical Household Members directory, Edit Member card, and Add Member card."""
    cur = current_member or {}
    cur_email = str(cur.get("email") or "").strip()
    cur_role = str(cur.get("role") or "adult").strip().lower()
    can_manage = cur_role in ("admin", "adult")
    inv_list = list(invites or [])
    active_inv_codes = ",".join(
        str(i.get("code") or "")
        for i in inv_list
        if i.get("code") and i.get("valid", i.get("status") != "redeemed")
    )
    admin_opt = '<option value="admin">Admin (Household Owner)</option>' if cur_role == "admin" else ""

    rows_html: list[str] = []
    for m in members:
        mid = escape(str(m.get("id") or ""))
        mname = str(m.get("display_name") or m.get("name") or "")
        mname_esc = escape(mname)
        mshort = str(m.get("short_name") or "").strip() or (
            mname.split("(")[0].strip().split()[0] if mname.split("(")[0].strip() else mname
        )
        mshort_esc = escape(mshort)
        base_mname = mname.split("(")[0].strip().lower()
        memail = str(m.get("email") or "")
        memail_esc = escape(memail)
        mrole = str(m.get("role") or "adult").lower()
        mrole_up = escape(mrole.upper())
        matching_invs = [
            i for i in inv_list
            if i.get("label") and str(i.get("label")).split("(")[0].strip().lower() == base_mname
        ]
        member_inv = next(
            (i for i in matching_invs if i.get("valid", i.get("status") != "redeemed")),
            matching_invs[0] if matching_invs else None,
        )
        is_pending_email = memail.endswith("@invite.local")
        has_redeemed_invite = any(
            (int(i.get("uses_count") or 0) > 0 or i.get("status") == "redeemed")
            for i in matching_invs
        )
        is_joined = (not is_pending_email) and (
            memail == cur_email
            or bool(m.get("google_vault_synced"))
            or bool(m.get("invite_accepted"))
            or has_redeemed_invite
        )

        email_badge = (
            '<span class="badge badge-orange" style="font-size: 0.6875rem;">Pending Invite</span>'
            if is_pending_email
            else f'<span style="font-size:0.78rem; color:var(--text-muted); font-family:var(--font-mono); word-break:break-all;">{memail_esc}</span>'
        )
        role_badge_cls = "badge-green" if mrole in ("admin", "adult", "editor") else "badge-blue"

        actions: list[str] = []
        if memail == cur_email:
            actions.append('<span class="badge badge-green" style="font-size: 0.6875rem;">Active Session</span>')
        else:
            if is_local_mode:
                actions.append(
                    f'<a href="/switch-member?email={memail_esc}" class="btn btn-secondary btn-sm" style="padding:3px 8px; font-size:0.75rem;">Switch To</a>'
                )
            if is_joined:
                actions.append('<span class="badge badge-green" style="font-size: 0.6875rem;">Invite Accepted</span>')
            elif can_manage:
                inv_valid = bool(member_inv and member_inv.get("valid", member_inv.get("status") != "redeemed"))
                inv_url = escape(str(member_inv.get("invite_url") or "")) if inv_valid and member_inv else ""
                actions.append(
                    f'<button type="button" class="btn btn-secondary btn-sm asst-member-invite-btn" data-member-id="{mid}" '
                    f'data-member-name="{mname_esc}" data-member-role="{escape(mrole)}" data-invite-url="{inv_url}" '
                    f'style="padding:3px 8px; font-size:0.75rem;" title="Copy Magic Invite link for {mname_esc} (onboards as {mrole_up})">Copy Invite Link</button>'
                )
                if inv_valid and member_inv and member_inv.get("code"):
                    ic = escape(str(member_inv.get("code")))
                    actions.append(
                        f'<button type="button" class="asst-icon-danger-btn asst-revoke-invite-btn" data-code="{ic}" '
                        f'title="Revoke active invite link ({ic})">Revoke Invite</button>'
                    )
        if can_manage or memail == cur_email:
            clean_email = "" if memail.endswith("@invite.local") else memail_esc
            actions.append(
                f'<button type="button" class="btn btn-secondary btn-sm asst-edit-member-btn" data-member-id="{mid}" '
                f'data-member-name="{mname_esc}" data-member-short-name="{mshort_esc}" data-member-email="{clean_email}" data-member-role="{escape(mrole)}" '
                f'style="padding:3px 8px; font-size:0.75rem;" title="Edit {mname_esc}">Edit</button>'
            )
        if can_manage and memail != cur_email:
            actions.append(
                f'<button type="button" class="asst-icon-danger-btn asst-remove-member-btn" data-member-id="{mid}" '
                f'title="Remove {mname_esc}">&times;</button>'
            )

        rows_html.append(
            f'<div class="asst-member-row" id="member-row-{mid}" style="box-sizing: border-box; width: 100%;">'
            '<div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap; min-width:0; flex:1 1 200px;">'
            f'<strong class="asst-member-display-name" style="font-size:0.85rem; word-break:break-word;">{mname_esc}</strong>'
            f'<span class="badge badge-blue asst-member-short-name" style="font-size:0.6875rem;" title="Chat short name">@{mshort_esc}</span>'
            f"{email_badge}"
            f'<span class="badge {role_badge_cls}" style="font-size: 0.6875rem;">{mrole_up}</span>'
            "</div>"
            f'<div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">{"".join(actions)}</div>'
            "</div>"
        )

    add_card_html = (
        '<div class="asst-subcard" style="margin-bottom: 18px;">'
        '<span class="micro-label">ADD FAMILY MEMBER</span>'
        '<form id="asst-add-member-form" class="asst-input-row" style="margin-top: 6px;">'
        '<input id="asst-new-member-name" class="asst-text-input" type="text" maxlength="100" placeholder="Full Name (e.g. Mary Beth Smith)" required style="max-width:170px;">'
        '<input id="asst-new-member-short-name" class="asst-text-input" type="text" maxlength="40" placeholder="Short Name (e.g. Mary Beth)" style="max-width:150px;">'
        '<input id="asst-new-member-email" class="asst-text-input" type="email" maxlength="254" placeholder="Google Email (optional — or use Copy Invite Link)">'
        '<select id="asst-new-member-role" class="asst-select" aria-label="Member Role">'
        '<option value="adult">Adult (Parents Scope)</option>'
        '<option value="kid">Kid (Family Scope Only)</option>'
        f"{admin_opt}</select>"
        '<button class="btn btn-primary btn-sm" type="submit">+ Add Member</button>'
        "</form></div>"
        if can_manage
        else ""
    )

    return Markup(
        '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">'
        "<div>"
        '<h3 style="font-size: 0.9375rem; margin: 0;">Household Members</h3>'
        '<p class="text-muted" style="font-size: 0.75rem; margin: 2px 0 0 0;">Add family members and click <strong>Copy Invite Link</strong> next to any member so they can sign in with Google.</p>'
        "</div></div>"
        '<div id="asst-edit-member-card" class="asst-subcard" style="display: none; position: relative; border-color: var(--brand-primary);">'
        '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">'
        '<h4 style="margin: 0; font-size: 0.875rem; color: var(--brand-primary); font-weight: 700;">Edit Family Member</h4>'
        '<button type="button" id="btn-close-edit-member" class="custom-modal-close-btn" style="position: static; width: 28px; height: 28px;" aria-label="Close Edit Member">'
        '<svg class="hvl-icon" width="15" height="15"><use href="/common/icons.svg#icon-close"></use></svg></button></div>'
        '<form id="asst-edit-member-form" style="display: flex; flex-direction: column; gap: 10px; width: 100%; box-sizing: border-box;">'
        '<input type="hidden" id="asst-edit-member-id">'
        '<div style="display: flex; flex-wrap: wrap; gap: 10px; width: 100%; box-sizing: border-box;">'
        '<div style="flex: 1 1 180px; min-width: 0; max-width: 100%;">'
        '<label style="font-size: 0.75rem; font-weight: 600; display: block; margin-bottom: 4px; color: var(--text-secondary);">Full Name</label>'
        '<input type="text" id="asst-edit-member-name" maxlength="100" required class="asst-text-input" style="width: 100%; min-width: 0; box-sizing: border-box;"></div>'
        '<div style="flex: 1 1 150px; min-width: 0; max-width: 100%;">'
        '<label style="font-size: 0.75rem; font-weight: 600; display: block; margin-bottom: 4px; color: var(--text-secondary);">Short Name (Chat)</label>'
        '<input type="text" id="asst-edit-member-short-name" maxlength="40" placeholder="Auto (e.g. Alex, Sam)" class="asst-text-input" style="width: 100%; min-width: 0; box-sizing: border-box;"></div>'
        '<div style="flex: 1 1 190px; min-width: 0; max-width: 100%;">'
        '<label style="font-size: 0.75rem; font-weight: 600; display: block; margin-bottom: 4px; color: var(--text-secondary);">Google Email</label>'
        '<input type="email" id="asst-edit-member-email" class="asst-text-input" style="width: 100%; min-width: 0; box-sizing: border-box; word-break: break-all;"></div>'
        '<div style="flex: 1 1 140px; min-width: 0; max-width: 100%;">'
        '<label style="font-size: 0.75rem; font-weight: 600; display: block; margin-bottom: 4px; color: var(--text-secondary);">Role</label>'
        '<select id="asst-edit-member-role" class="asst-select" style="width: 100%; min-width: 0; box-sizing: border-box;">'
        '<option value="adult">Adult (Parents Scope)</option>'
        '<option value="kid">Kid (Family Scope Only)</option>'
        f"{admin_opt}</select></div></div>"
        '<div style="display: flex; gap: 8px; flex-wrap: wrap; margin-top: 2px;">'
        '<button type="submit" class="btn btn-primary btn-sm">Save Changes</button>'
        '<button type="button" id="btn-cancel-edit-member" class="btn btn-secondary btn-sm">Cancel</button></div></form>'
        '<div id="asst-edit-member-status" style="font-size: 0.8rem; margin-top: 8px; font-weight: 600;"></div></div>'
        f'<div id="asst-members-directory" data-active-invites="{escape(active_inv_codes)}" style="margin-bottom: 12px; width: 100%; box-sizing: border-box;">'
        f'{"".join(rows_html)}</div>'
        f"{add_card_html}"
    )


def hvl_household_groups_section(
    groups: Iterable[dict[str, Any]] | None,
    members: Iterable[dict[str, Any]],
    current_member: dict[str, Any] | None = None,
) -> Markup:
    """Emit canonical Household Groups & Access Control section."""
    cur = current_member or {}
    cur_email = str(cur.get("email") or "").strip()
    cur_role = str(cur.get("role") or "adult").strip().lower()
    can_manage = cur_role in ("admin", "adult")
    grp_list = list(groups or [])
    mem_list = list(members or [])

    edit_cbs = "".join(
        '<label class="asst-check-chip">'
        f'<input type="checkbox" class="asst-checkbox asst-edit-group-member-cb" value="{escape(str(m.get("email") or ""))}">'
        f'<span>{escape(str(m.get("display_name") or m.get("name") or ""))}</span></label>'
        for m in mem_list
    )
    new_cbs = "".join(
        '<label class="asst-check-chip">'
        f'<input type="checkbox" class="asst-checkbox asst-new-group-member-cb" value="{escape(str(m.get("email") or ""))}"'
        f'{" checked" if str(m.get("email") or "") == cur_email else ""}>'
        f'<span>{escape(str(m.get("display_name") or m.get("name") or ""))}</span></label>'
        for m in mem_list
    )

    edit_card_html = (
        '<div id="asst-edit-group-card" class="asst-subcard" style="display: none; position: relative; border-color: var(--brand-primary);">'
        '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">'
        '<h4 style="margin: 0; font-size: 0.875rem; color: var(--brand-primary); font-weight: 700;">Edit Group</h4>'
        '<button type="button" id="btn-close-edit-group" class="custom-modal-close-btn" style="position: static; width: 28px; height: 28px;" aria-label="Close Edit Group">'
        '<svg class="hvl-icon" width="15" height="15"><use href="/common/icons.svg#icon-close"></use></svg></button></div>'
        '<form id="asst-edit-group-form" style="display: flex; flex-direction: column; gap: 8px;">'
        '<input type="hidden" id="asst-edit-group-id">'
        "<div>"
        '<label for="asst-edit-group-name" style="font-size:0.75rem; font-weight:600; display:block; margin-bottom:4px; color:var(--text-secondary);">Group Name</label>'
        '<input type="text" id="asst-edit-group-name" maxlength="60" required class="asst-text-input" style="width: 100%; box-sizing: border-box;"></div>'
        "<div>"
        '<label style="font-size:0.75rem; font-weight:600; display:block; margin-bottom:4px; color:var(--text-secondary);">Group Members</label>'
        f'<div id="asst-edit-group-members-grid" style="display: flex; flex-wrap: wrap; gap: 6px;">{edit_cbs}</div></div>'
        '<div style="display: flex; gap: 8px; margin-top: 4px;">'
        '<button type="submit" class="btn btn-primary btn-sm">Save Group</button>'
        '<button type="button" id="btn-cancel-edit-group" class="btn btn-secondary btn-sm">Cancel</button></div></form>'
        '<div id="asst-edit-group-status" style="font-size: 0.8rem; margin-top: 6px; font-weight: 600;"></div></div>'
        if can_manage
        else ""
    )

    grp_rows: list[str] = []
    for g in grp_list:
        gid = escape(str(g.get("id") or ""))
        gname = escape(str(g.get("name") or ""))
        gslug = escape(str(g.get("slug") or ""))
        gsys = "1" if g.get("is_system") else "0"
        gmem_emails = escape(",".join(str(e) for e in (g.get("member_emails") or [])))
        pills = "".join(
            f'<span style="font-size:0.75rem; background:var(--bg-surface-elevated); padding:2px 6px; border-radius:4px; border:1px solid var(--border-color);">{escape(str(mem.get("display_name") or mem.get("name") or mem.get("email") or ""))}</span>'
            for mem in (g.get("members") or [])
        )
        act_html = ""
        if can_manage:
            del_html = (
                f'<button type="button" class="asst-icon-danger-btn asst-delete-group-btn" data-group-id="{gid}" title="Delete {gname}">&times;</button>'
                if g.get("can_delete")
                else '<span class="badge badge-green" style="font-size:0.6875rem;">Protected</span>'
            )
            act_html = (
                f'<button type="button" class="btn btn-secondary btn-sm asst-edit-group-btn" data-group-id="{gid}" '
                f'data-group-name="{gname}" data-group-slug="{gslug}" data-group-system="{gsys}" data-group-members="{gmem_emails}" '
                f'style="padding:3px 8px; font-size:0.75rem;" title="Edit {gname}">Edit</button>{del_html}'
            )
        grp_rows.append(
            f'<div class="asst-member-row" id="group-row-{gid}">'
            '<div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap; min-width:0; flex:1 1 200px;">'
            f'<strong style="font-size:0.85rem;">{gname}</strong>'
            f'<span class="badge badge-blue" style="font-size: 0.6875rem;">{escape(str(g.get("slug") or "").upper())}</span>'
            f'<div style="display:inline-flex; gap:4px; flex-wrap:wrap;">{pills}</div></div>'
            f'<div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">{act_html}</div></div>'
        )

    create_form_html = (
        '<form id="asst-create-group-form" class="asst-subcard" style="margin-bottom: 0; display:flex; flex-direction:column; gap:8px;">'
        '<span class="micro-label" style="margin-bottom: 0;">CREATE ACCESS GROUP</span>'
        '<div class="asst-input-row" style="margin: 0;">'
        '<input id="asst-new-group-name" class="asst-text-input" type="text" maxlength="60" placeholder="New group name (e.g. Nanny, Personal Assistant, Adults)..." required style="flex:1;">'
        '<button class="btn btn-primary btn-sm" type="submit">+ Create Group</button></div>'
        '<div style="display:flex; flex-wrap:wrap; gap:6px; align-items:center; font-size:0.78rem;">'
        '<span style="color:var(--text-secondary); font-weight:600; margin-right:2px;">Initial Members:</span>'
        f"{new_cbs}</div></form>"
        if can_manage
        else ""
    )

    return Markup(
        '<div style="border-top: 1px solid var(--border-subtle); padding-top: 16px;">'
        '<div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 10px;">'
        "<div>"
        '<h3 style="font-size: 0.9375rem; margin: 0;">Household Groups &amp; Access Control</h3>'
        '<p class="text-muted" style="font-size: 0.75rem; margin: 2px 0 0 0;">Organize family members into custom access control groups (e.g. Nanny, Personal Assistant, Adults).</p>'
        f'</div><span class="badge badge-blue">{len(grp_list)} Groups</span></div>'
        f"{edit_card_html}"
        f'<div id="asst-groups-directory" style="margin-bottom: 12px;">{"".join(grp_rows)}</div>'
        f"{create_form_html}</div>"
    )
