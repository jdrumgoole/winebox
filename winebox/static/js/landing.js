/**
 * Landing Page JavaScript
 * Handles mobile menu toggle and smooth scrolling.
 */

// Mobile menu toggle
document.querySelector('.mobile-menu-toggle').addEventListener('click', function() {
    document.querySelector('.header-nav').classList.toggle('active');
    this.classList.toggle('active');
});

// Smooth scroll for anchor links
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function(e) {
        const href = this.getAttribute('href');
        if (href.length > 1) {
            e.preventDefault();
            document.querySelector(href).scrollIntoView({
                behavior: 'smooth'
            });
        }
    });
});
