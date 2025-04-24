function formatTimeAgo(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const diff = Math.floor((now - date) / 1000); // in seconds

    if (diff < 60) return 'Just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
}

function updateNotificationBadge() {
    fetch('/api/notifications/unread-count')
        .then(res => res.json())
        .then(data => {
            const badge = document.getElementById('notificationBadge');
            if (data.count > 0) {
                badge.textContent = data.count;
                badge.style.display = 'block';
            } else {
                badge.style.display = 'none';
            }
        })
        .catch(error => console.error('Error fetching unread count:', error));
}

function loadNotificationList() {
    fetch('/api/notifications?limit=5')
        .then(res => res.json())
        .then(notifications => {
            const container = document.getElementById('notificationList');
            container.innerHTML = '';

            if (notifications.length === 0) {
                container.innerHTML = '<div class="px-3 py-2 text-muted">No notifications</div>';
                return;
            }

            notifications.forEach(notif => {
                const item = document.createElement('div');
                item.className = `dropdown-item ${notif.is_read ? '' : 'fw-bold'}`;
                item.style.cursor = 'pointer';
                item.innerHTML = `
                    <div class="d-flex justify-content-between">
                        <span>${notif.message}</span>
                        <small class="text-muted">${formatTimeAgo(notif.created_at)}</small>
                    </div>
                `;

                item.addEventListener('click', (e) => {
                    e.preventDefault();
                    const form = document.createElement('form');
                    form.method = 'POST';
                    form.action = `/notifications/mark-read/${notif.notification_id}`;

                    const csrfInput = document.createElement('input');
                    csrfInput.type = 'hidden';
                    csrfInput.name = 'csrf_token';
                    csrfInput.value = document.getElementById('csrf-token').textContent;
                    form.appendChild(csrfInput);

                    document.body.appendChild(form);
                    form.submit();
                });

                container.appendChild(item);
            });
        })
        .catch(error => {
            console.error('Error loading notifications:', error);
            document.getElementById('notificationList').innerHTML = '<div class="px-3 py-2 text-danger">Error loading notifications</div>';
        });
}

document.addEventListener('DOMContentLoaded', function () {
    if (document.getElementById('notificationBadge') && document.getElementById('notificationList')) {
        updateNotificationBadge();
        loadNotificationList();

        setInterval(updateNotificationBadge, 30000);

        document.getElementById('notificationDropdown').addEventListener('shown.bs.dropdown', loadNotificationList);
    }
});
