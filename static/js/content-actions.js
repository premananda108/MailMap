// Function for voting (like/dislike)
function voteContent(contentId, voteValue, event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }

    if (!currentUser) {
        console.log("Waiting for authentication...");
        setTimeout(() => voteContent(contentId, voteValue, event), 500);
        return;
    }

    fetch(`/api/content/${contentId}/vote`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-User-ID': currentUser.uid
        },
        body: JSON.stringify({ vote: voteValue, userId: currentUser.uid })
    })
    .then(response => {
        if (!response.ok) throw new Error(`Server responded with status: ${response.status}`);
        return response.json();
    })
    .then(data => {
        if (data.status === 'success') {
            updateItemVoteCount(contentId, data.newVoteCount);

            let btn;
            if (event) btn = event.target.closest('.vote-btn');
            if (btn) {
                btn.classList.add('voted');
                setTimeout(() => btn.classList.remove('voted'), 500);
            }
        } else {
            console.error('Error voting:', data.message);
            alert('Failed to vote: ' + data.message);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('An error occurred while voting: ' + error.message);
    });
}

// Function for reporting content
function reportContent(contentId, event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }

    if (!currentUser) {
        console.log("Waiting for authentication...");
        setTimeout(() => reportContent(contentId, event), 500);
        return;
    }

    const reason = prompt('Please state the reason for your report:');
    if (reason === null) return;

    fetch(`/api/content/${contentId}/report`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-User-ID': currentUser.uid
        },
        body: JSON.stringify({ reason: reason, userId: currentUser.uid })
    })
    .then(response => {
        if (!response.ok) throw new Error(`Server responded with status: ${response.status}`);
        return response.json();
    })
    .then(data => {
        if (data.status === 'success') {
            alert('Thank you! Your report has been sent to the moderators.');
        } else {
            console.error('Error reporting:', data.message);
            alert('Failed to send report: ' + data.message);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('An error occurred while sending the report: ' + error.message);
    });
}

// Functions for add content form
function openAddContentForm() {
    if (!currentUser) {
        console.log("Waiting for authentication...");
        setTimeout(openAddContentForm, 500);
        return;
    }

    if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(function(position) {
            window.userLat = position.coords.latitude;
            window.userLng = position.coords.longitude;
            document.getElementById('add-content-form').style.display = 'block';
        }, function(error) {
            console.error("Error getting geolocation:", error);
            alert("To add a post, please allow access to your location.");
        });
    } else {
        alert("Your browser does not support geolocation.");
    }
}

function closeAddContentForm() {
    document.getElementById('add-content-form').style.display = 'none';
    document.getElementById('content-text').value = '';
    document.getElementById('content-image').value = '';
}

function submitContent() {
    if (!currentUser) {
        alert("You must be logged in to publish content.");
        return;
    }

    const text = document.getElementById('content-text').value;
    const imageFile = document.getElementById('content-image').files[0];

    if (!text && !imageFile) {
        alert("Add text or an image to publish.");
        return;
    }

    if (!window.userLat || !window.userLng) {
        alert("Could not determine your location. Please try again.");
        return;
    }

    const formData = new FormData();
    formData.append('text', text);
    if (imageFile) formData.append('image', imageFile);
    formData.append('latitude', window.userLat);
    formData.append('longitude', window.userLng);
    formData.append('userId', currentUser.uid);

    fetch('/api/content/create', {
        method: 'POST',
        headers: { 'X-User-ID': currentUser.uid },
        body: formData
    })
    .then(response => {
        if (!response.ok) throw new Error(`Server responded with status: ${response.status}`);
        return response.json();
    })
    .then(data => {
        if (data.status === 'success') {
            alert('Post added successfully!');
            closeAddContentForm();

            // Create a new item object and add it to the map
            const newItem = {
                itemId: data.contentId,
                text: text,
                imageUrl: null, // We'll update this after page reload
                latitude: window.userLat,
                longitude: window.userLng,
                timestamp: new Date(),
                voteCount: 0,
                reportedCount: 0,
                status: 'published'
            };

            // Add the new item to the map
            addItemToMap(newItem);

            // Center the map on the new item
            map.setCenter({lat: window.userLat, lng: window.userLng});
            map.setZoom(15);
        } else {
            alert(`Error: ${data.message}`);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('An error occurred while adding the post: ' + error.message);
    });
}

// Function to copy to clipboard
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        alert('Link copied to clipboard!');
    }).catch(err => {
        console.error('Failed to copy link: ', err);
    });
}

// Function for sharing on social media
function shareOnSocialMedia(platform, url, title, imageUrl) {
    // Validate input data and convert to string
    url = String(url || window.location.href);
    title = String(title || 'Like me! Post on MailMap'); // Default title in English
    imageUrl = String(imageUrl || '');

    // Clean potential problematic characters from URL
    // and apply encodeURIComponent only to cleaned data
    let cleanTitle = title.replace(/[\"'`]/g, '');
    let shareUrl;

    try {
        switch(platform) {
            case 'vk':
                shareUrl = 'https://vk.com/share.php?url=' + encodeURIComponent(url) + 
                           '&title=' + encodeURIComponent(cleanTitle) + 
                           '&image=' + encodeURIComponent(imageUrl);
                break;
            case 'telegram':
                shareUrl = 'https://t.me/share/url?url=' + encodeURIComponent(url) + 
                           '&text=' + encodeURIComponent(cleanTitle);
                break;
            case 'whatsapp':
                shareUrl = 'https://api.whatsapp.com/send?text=' + 
                           encodeURIComponent(cleanTitle + ' ' + url);
                break;
            case 'facebook':
                shareUrl = 'https://www.facebook.com/sharer/sharer.php?u=' + 
                           encodeURIComponent(url);
                break;
            case 'x':
                shareUrl = 'https://twitter.com/intent/tweet?url=' + 
                           encodeURIComponent(url) + '&text=' + 
                           encodeURIComponent(cleanTitle);
                break;
            default:
                console.error('Unknown platform:', platform);
                return;
        }

        // Open sharing window
        window.open(shareUrl, '_blank', 'width=600,height=400,resizable=yes,scrollbars=yes');

        // For analytics - can add tracking for sharing events
        console.log(`Shared on ${platform}: ${url}`);
    } catch (e) {
        console.error('Error creating share link:', e);
        alert('Failed to share. Please try again later.');
    }
}