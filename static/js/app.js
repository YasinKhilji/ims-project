// Search functionality for products
document.getElementById('searchProducts')?.addEventListener('input', function() {
    const searchTerm = this.value.toLowerCase();
    document.querySelectorAll('#productsTable tbody tr').forEach(row => {
        row.style.display = row.textContent.toLowerCase().includes(searchTerm) ? '' : 'none';
    });
});

// Search and filter functionality for orders
document.getElementById('searchOrders')?.addEventListener('input', function() {
    filterOrders();
});

document.getElementById('filterStatus')?.addEventListener('change', function() {
    filterOrders();
});

document.getElementById('resetFilters')?.addEventListener('click', function() {
    document.getElementById('searchOrders').value = '';
    document.getElementById('filterStatus').value = '';
    filterOrders();
});

function filterOrders() {
    const searchTerm = document.getElementById('searchOrders').value.toLowerCase();
    const statusFilter = document.getElementById('filterStatus').value;
    
    document.querySelectorAll('#ordersTable tbody tr').forEach(row => {
        const text = row.textContent.toLowerCase();
        const status = row.querySelector('td:nth-child(5)')?.textContent.trim() || '';
        
        const matchesSearch = text.includes(searchTerm);
        const matchesStatus = statusFilter === '' || status === statusFilter;
        
        row.style.display = (matchesSearch && matchesStatus) ? '' : 'none';
    });
}