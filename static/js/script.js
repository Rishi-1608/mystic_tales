document.addEventListener('DOMContentLoaded', function() {
    const chatMessages = document.getElementById('chat-messages');
    const userInput = document.getElementById('user-input');
    const sendButton = document.getElementById('send-button');

    const featureCards = document.querySelectorAll('.feature-card');
    
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const animation = entry.target.getAttribute('data-animation');
                const delay = entry.target.getAttribute('data-delay') || '0s';
                entry.target.style.animationDelay = delay;
                entry.target.classList.add(animation);
                observer.unobserve(entry.target);
            }
        });
    }, { threshold: 0.1 });
    
    featureCards.forEach(card => {
        observer.observe(card);
    });
    
    // Smooth scroll for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function(e) {
            e.preventDefault();
            document.querySelector(this.getAttribute('href')).scrollIntoView({
                behavior: 'smooth'
            });
        });
    });

    function scrollToBottom() {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function addMessage(sender, text) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${sender}-message`;
        messageDiv.innerHTML = `
            <div class="message-sender">${sender === 'user' ? 'You' : document.querySelector('.character-header h2').textContent}</div>
            <div class="message-content">${text}</div>
        `;
        chatMessages.appendChild(messageDiv);
        scrollToBottom();
    }

    function showTypingIndicator() {
        const typingDiv = document.createElement('div');
        typingDiv.className = 'message bot-message typing-indicator';
        typingDiv.innerHTML = `
            <div class="message-sender">${document.querySelector('.character-header h2').textContent}</div>
            <div class="message-content">...</div>
        `;
        chatMessages.appendChild(typingDiv);
        scrollToBottom();
        return typingDiv;
    }

    function removeTypingIndicator() {
        const typing = document.querySelector('.typing-indicator');
        if (typing) typing.remove();
    }

    function sendMessage() {
        const message = userInput.value.trim();
        if (message) {
            addMessage('user', message);
            userInput.value = '';
            
            const typing = showTypingIndicator();
            
            fetch('/send_message', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ message: message })
            })
            .then(response => {
                if (!response.ok) {
                    return response.json().then(err => { throw new Error(err.error || 'Request failed'); });
                }
                return response.json();
            })
            .then(data => {
                removeTypingIndicator();
                if (data.error) throw new Error(data.error);
                addMessage(data.sender, data.text);
            })
            .catch(error => {
                removeTypingIndicator();
                addMessage('error', error.message);
                console.error('Chat error:', error);
            });
        }
    }

    // Event listeners
    sendButton.addEventListener('click', sendMessage);
    userInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            sendMessage();
        }
    });

    // Initial scroll to bottom
    scrollToBottom();
});