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

// Function for sharing on social media
function shareOnSocialMedia(platform, url, title, imageUrl, event) {
    // Предотвращаем распространение события, если оно передано
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
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
        console.log('Sharing data:', { platform, url, cleanTitle, imageUrl, shareUrl });
        window.open(shareUrl, '_blank', 'width=600,height=400,resizable=yes,scrollbars=yes');

        // For analytics - can add tracking for sharing events
        console.log(`Shared on ${platform}: ${url}`);
    } catch (e) {
        console.error('Error creating share link:', e);
        alert('Failed to share. Please try again later.');
    }
}