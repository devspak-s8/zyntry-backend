from __future__ import annotations

from app.services.runtime_assistant.schemas import ActionType, PermissionCheck, UserRole


class PermissionDeniedError(Exception):
    def __init__(self, required: UserRole, current: UserRole, action: str) -> None:
        self.required_role = required
        self.current_role = current
        self.action = action
        super().__init__(
            f"Permission denied: {action} requires {required.value}, "
            f"but user has {current.value}"
        )


ROLE_HIERARCHY: dict[UserRole, int] = {
    UserRole.VIEWER: 0,
    UserRole.DEVELOPER: 1,
    UserRole.ADMIN: 2,
    UserRole.OWNER: 3,
}


def get_role_level(role: UserRole) -> int:
    return ROLE_HIERARCHY.get(role, -1)


def has_permission(
    user_role: UserRole,
    required_role: UserRole,
    action_type: ActionType | None = None,
    dangerous: bool = False,
) -> PermissionCheck:
    user_level = get_role_level(user_role)
    required_level = get_role_level(required_role)

    if dangerous and user_level < get_role_level(UserRole.ADMIN):
        return PermissionCheck(
            allowed=False,
            required_role=required_role,
            user_role=user_role,
            reason="Dangerous actions require admin role or higher",
        )

    if action_type == ActionType.ADMIN and user_level < get_role_level(UserRole.ADMIN):
        return PermissionCheck(
            allowed=False,
            required_role=required_role,
            user_role=user_role,
            reason="Admin actions require admin role or higher",
        )

    if action_type == ActionType.EXECUTE and user_level < get_role_level(UserRole.DEVELOPER):
        return PermissionCheck(
            allowed=False,
            required_role=required_role,
            user_role=user_role,
            reason="Execute actions require developer role or higher",
        )

    if user_level < required_level:
        return PermissionCheck(
            allowed=False,
            required_role=required_role,
            user_role=user_role,
            reason=f"Insufficient permissions: requires {required_role.value}",
        )

    return PermissionCheck(
        allowed=True,
        required_role=required_role,
        user_role=user_role,
    )


def check_tool_permission(
    user_role: UserRole,
    tool_name: str,
    tools: list[dict[str, Any]],
) -> PermissionCheck:
    tool_map = {t["name"]: t for t in tools}
    tool = tool_map.get(tool_name)

    if not tool:
        return PermissionCheck(
            allowed=False,
            required_role=UserRole.VIEWER,
            user_role=user_role,
            reason=f"Unknown tool: {tool_name}",
        )

    required_role = tool.get("required_permission", UserRole.DEVELOPER)
    action_type = tool.get("action_type", ActionType.READ)
    dangerous = tool.get("dangerous", False)

    return has_permission(
        user_role=user_role,
        required_role=required_role,
        action_type=action_type,
        dangerous=dangerous,
    )


def filter_available_tools(
    user_role: UserRole,
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    available = []
    for tool in tools:
        check = check_tool_permission(user_role, tool["name"], tools)
        if check.allowed:
            available.append(tool)
    return available
