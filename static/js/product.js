/* static/js/product.js */

document.addEventListener('DOMContentLoaded', function () {
    const selectProductBtn = document.getElementById('select-product-btn');
    const modal = document.getElementById('product-list-modal');
    const closeModalBtn = document.querySelector('.close');
    const productList = document.getElementById('product-list');
    const productDisplay = document.getElementById('product-display');

    // Function to fetch all products
    async function fetchProducts() {
        try {
            const response = await fetch('/api/products');
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            const products = await response.json();
            return products;
        } catch (error) {
            console.error('Error fetching products:', error);
            alert('Failed to load products. Please try again later.');
            return [];
        }
    }

    // Function to populate the product list in the modal
    function populateProductList(products) {
        // Clear any existing products in the list
        productList.innerHTML = '';

        products.forEach(product => {
            const listItem = document.createElement('li');
            listItem.className = 'list-group-item list-group-item-action';
            listItem.textContent = product.name;
            listItem.dataset.productId = product._id; // Store product ID for later use

            // Add click event listener to each product
            listItem.addEventListener('click', () => {
                selectProduct(product);
                closeModal();
            });

            productList.appendChild(listItem);
        });
    }

    // Function to handle product selection
    function selectProduct(product) {
        // Update the product title
        const currentTitle = document.querySelector('h1.my-4.text-center');
        currentTitle.textContent = `Order Now: ${product.name}`;

        // Update the product display
        productDisplay.innerHTML = `
            <div class="col-md-6 col-lg-4 mb-4">
                <div class="card h-100 text-center">
                    <!-- Dynamic Image -->
                    <img src="${product.image_url}" class="card-img-top" alt="${product.name}">
                    <div class="card-body">
                        <h5 class="card-title">${product.name}</h5>
                    </div>
                    <div class="card-footer">
                        <p class="card-text"><strong>Price: $${product.price.toFixed(2)}</strong></p>
                        <div class="product-buttons">
                            <!-- View Details button -->
                            <button
                                class="btn btn-product-view-details"
                                type="button"
                                data-toggle="collapse"
                                data-target="#collapse${product._id}"
                                aria-expanded="false"
                                aria-controls="collapse${product._id}"
                            >
                                View Details
                            </button>
                            <!-- Add to Cart button -->
                            <a
                                href="/customer/add_to_cart/${product._id}"
                                class="btn btn-book-now"
                            >
                                Book Now
                            </a>
                        </div>
                    </div>
                    
                    <!-- Collapsible content -->
                    <div class="collapse" id="collapse${product._id}">
                        <div class="card card-body">
                            <!-- Detailed description -->
                            <p>${product.description}</p>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    // Function to open the modal
    async function openModal() {
        const products = await fetchProducts();
        if (products.length > 0) {
            populateProductList(products);
            modal.style.display = 'block';
        }
    }

    // Function to close the modal
    function closeModal() {
        modal.style.display = 'none';
    }

    // Event listener for opening the modal
    selectProductBtn.addEventListener('click', openModal);

    // Event listener for closing the modal
    closeModalBtn.addEventListener('click', closeModal);

    // Close the modal when clicking outside the modal content
    window.addEventListener('click', function (event) {
        if (event.target == modal) {
            closeModal();
        }
    });
});

