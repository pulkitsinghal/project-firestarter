/**
 * Visual Cursor Overlay for Demo Recordings
 * 
 * Injects a custom cursor and click animations into the browser page
 * to provide visual feedback during automation.
 * 
 * Features:
 * - Large custom cursor (2x normal size)
 * - Ripple/radar click animations
 * - Smooth cursor movements
 * - Works with keyboard navigation
 */

(function() {
    'use strict';
    
    // Create overlay container
    const overlay = document.createElement('div');
    overlay.id = 'demo-visual-overlay';
    overlay.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100vw;
        height: 100vh;
        pointer-events: none;
        z-index: 999999;
        overflow: hidden;
    `;
    
    // Create custom cursor
    const cursor = document.createElement('div');
    cursor.id = 'demo-cursor';
    cursor.style.cssText = `
        position: absolute;
        width: 32px;
        height: 32px;
        background: radial-gradient(circle, #FF4444 0%, #FF0000 70%, transparent 100%);
        border: 3px solid white;
        border-radius: 50%;
        transform: translate(-50%, -50%);
        transition: all 0.1s ease-out;
        box-shadow: 0 0 10px rgba(255, 0, 0, 0.5), 0 0 20px rgba(255, 0, 0, 0.3);
        display: none;
    `;
    
    // Add pointer triangle
    const pointer = document.createElement('div');
    pointer.style.cssText = `
        position: absolute;
        bottom: -8px;
        left: 50%;
        transform: translateX(-50%);
        width: 0;
        height: 0;
        border-left: 8px solid transparent;
        border-right: 8px solid transparent;
        border-top: 12px solid #FF0000;
        filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.3));
    `;
    cursor.appendChild(pointer);
    
    overlay.appendChild(cursor);
    document.body.appendChild(overlay);
    
    // Cursor state
    let cursorX = window.innerWidth / 2;
    let cursorY = window.innerHeight / 2;
    let isVisible = false;
    
    // Animation queue
    const animations = [];
    
    /**
     * Show the custom cursor
     */
    function showCursor() {
        cursor.style.display = 'block';
        isVisible = true;
    }
    
    /**
     * Hide the custom cursor
     */
    function hideCursor() {
        cursor.style.display = 'none';
        isVisible = false;
    }
    
    /**
     * Move cursor to position
     * @param {number} x - Target X coordinate
     * @param {number} y - Target Y coordinate
     * @param {number} duration - Animation duration in ms
     */
    function moveCursor(x, y, duration = 300) {
        showCursor();
        
        cursor.style.transition = `all ${duration}ms ease-in-out`;
        cursor.style.left = `${x}px`;
        cursor.style.top = `${y}px`;
        
        cursorX = x;
        cursorY = y;
    }
    
    /**
     * Create click ripple animation
     * @param {number} x - X coordinate
     * @param {number} y - Y coordinate
     */
    function createClickRipple(x, y) {
        const ripple = document.createElement('div');
        ripple.style.cssText = `
            position: absolute;
            left: ${x}px;
            top: ${y}px;
            width: 0;
            height: 0;
            border-radius: 50%;
            border: 3px solid #FF0000;
            transform: translate(-50%, -50%);
            animation: ripple-expand 0.8s ease-out forwards;
            pointer-events: none;
        `;
        
        overlay.appendChild(ripple);
        
        // Remove after animation
        setTimeout(() => {
            ripple.remove();
        }, 800);
    }
    
    /**
     * Create multiple ripple waves
     * @param {number} x - X coordinate
     * @param {number} y - Y coordinate
     * @param {number} count - Number of ripples
     */
    function createMultipleRipples(x, y, count = 3) {
        for (let i = 0; i < count; i++) {
            setTimeout(() => {
                createClickRipple(x, y);
            }, i * 150);
        }
    }
    
    /**
     * Pulse the cursor (for keyboard actions)
     */
    function pulseCursor() {
        cursor.style.transform = 'translate(-50%, -50%) scale(1.5)';
        setTimeout(() => {
            cursor.style.transform = 'translate(-50%, -50%) scale(1)';
        }, 200);
    }
    
    /**
     * Show visual feedback for click action
     * @param {number} x - X coordinate (optional, uses current if not provided)
     * @param {number} y - Y coordinate (optional, uses current if not provided)
     */
    function showClickFeedback(x = cursorX, y = cursorY) {
        // Move cursor if coordinates provided
        if (x !== cursorX || y !== cursorY) {
            moveCursor(x, y, 300);
            setTimeout(() => {
                pulseCursor();
                createMultipleRipples(x, y);
            }, 350);
        } else {
            pulseCursor();
            createMultipleRipples(x, y);
        }
    }
    
    /**
     * Show visual feedback for keyboard action
     * @param {string} key - Key name
     * @param {number} x - Optional X coordinate to move cursor to
     * @param {number} y - Optional Y coordinate to move cursor to
     */
    function showKeyboardFeedback(key, x = null, y = null) {
        if (x !== null && y !== null) {
            moveCursor(x, y, 300);
        }
        
        // Show key press indicator
        const keyIndicator = document.createElement('div');
        keyIndicator.textContent = key;
        keyIndicator.style.cssText = `
            position: absolute;
            left: ${x || cursorX}px;
            top: ${(y || cursorY) - 50}px;
            transform: translateX(-50%);
            background: rgba(0, 0, 0, 0.8);
            color: white;
            padding: 8px 16px;
            border-radius: 8px;
            font-family: monospace;
            font-size: 16px;
            font-weight: bold;
            animation: key-fade 1s ease-out forwards;
            pointer-events: none;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        `;
        
        overlay.appendChild(keyIndicator);
        
        setTimeout(() => {
            keyIndicator.remove();
        }, 1000);
        
        pulseCursor();
    }
    
    // Add CSS animations
    const style = document.createElement('style');
    style.textContent = `
        @keyframes ripple-expand {
            0% {
                width: 0;
                height: 0;
                opacity: 1;
            }
            100% {
                width: 200px;
                height: 200px;
                opacity: 0;
            }
        }
        
        @keyframes key-fade {
            0% {
                opacity: 1;
                transform: translateX(-50%) translateY(0);
            }
            100% {
                opacity: 0;
                transform: translateX(-50%) translateY(-20px);
            }
        }
    `;
    document.head.appendChild(style);
    
    // Expose API globally
    window.demoVisualCursor = {
        show: showCursor,
        hide: hideCursor,
        moveTo: moveCursor,
        click: showClickFeedback,
        keyboard: showKeyboardFeedback,
        isVisible: () => isVisible
    };
    
    console.log('✓ Demo visual cursor overlay loaded');
})();
