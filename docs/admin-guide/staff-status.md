# Staff Status

Staff Status provides department-based staff location and absence visibility.

## Core concepts

- Departments are usually derived from active users.
- Locations define where staff can mark themselves.
- Kiosk URLs allow staff to update status from shared devices.
- Board URLs display current department status.
- Absences override normal location status when active.

## Locations

Administrators can manage locations for each department. Locations support:

- Display name
- Short name
- Active/inactive state
- Drag-and-drop ordering

## Kiosk

The kiosk allows selected staff to update their status. It supports selecting one or more staff members and one or more locations.

### Tablet behavior

For iPads and tablets, the staff selector should be collapsible so locations remain easy to access. Users can open the staff picker, search/select staff, then choose locations and submit.

## Boards

The department board displays staff statuses and updates on an interval. It should avoid full-page refreshes and use lightweight data refreshes where possible.

## Public URLs

Kiosk and board URLs depend on the General Settings public base URL. If URLs are generated incorrectly, verify Settings -> General -> Public Base URL.

## Permissions

Staff Status should use department-scoped permissions so staff only operate departments they are authorized to manage.
