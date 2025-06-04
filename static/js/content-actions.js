// Function for voting (like/dislike)
function voteContent(contentId, voteValue, event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }

    if (!currentUser) {
        console.log("Ожидание аутентификации...");
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
            alert('Не удалось проголосовать: ' + data.message);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Произошла ошибка при голосовании: ' + error.message);
    });
}

// Function for reporting content
function reportContent(contentId, event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }

    if (!currentUser) {
        console.log("Ожидание аутентификации...");
        setTimeout(() => reportContent(contentId, event), 500);
        return;
    }

    const reason = prompt('Пожалуйста, укажите причину жалобы:');
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
            alert('Спасибо! Ваша жалоба отправлена модераторам.');
        } else {
            console.error('Error reporting:', data.message);
            alert('Не удалось отправить жалобу: ' + data.message);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Произошла ошибка при отправке жалобы: ' + error.message);
    });
}

// Functions for add content form
function openAddContentForm() {
    if (!currentUser) {
        console.log("Ожидание аутентификации...");
        setTimeout(openAddContentForm, 500);
        return;
    }

    if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(function(position) {
            window.userLat = position.coords.latitude;
            window.userLng = position.coords.longitude;
            document.getElementById('add-content-form').style.display = 'block';
        }, function(error) {
            console.error("Ошибка получения геолокации:", error);
            alert("Чтобы добавить публикацию, разрешите доступ к вашему местоположению.");
        });
    } else {
        alert("Ваш браузер не поддерживает определение геолокации.");
    }
}

function closeAddContentForm() {
    document.getElementById('add-content-form').style.display = 'none';
    document.getElementById('content-text').value = '';
    document.getElementById('content-image').value = '';
}

function submitContent() {
    if (!currentUser) {
        alert("Необходимо авторизоваться для публикации контента.");
        return;
    }

    const text = document.getElementById('content-text').value;
    const imageFile = document.getElementById('content-image').files[0];

    if (!text && !imageFile) {
        alert("Добавьте текст или изображение для публикации.");
        return;
    }

    if (!window.userLat || !window.userLng) {
        alert("Не удалось определить ваше местоположение. Попробуйте еще раз.");
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
            alert('Публикация успешно добавлена!');
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
            alert(`Ошибка: ${data.message}`);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Произошла ошибка при добавлении публикации: ' + error.message);
    });
}

// Функция для копирования в буфер обмена
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        alert('Ссылка скопирована в буфер обмена!');
    }).catch(err => {
        console.error('Не удалось скопировать ссылку: ', err);
    });
}

// Функция для шеринга в социальных сетях
function shareOnSocialMedia(platform, url, title, imageUrl) {
    // Проверяем входные данные и приводим к строке
    url = String(url || window.location.href);
    title = String(title || 'Лайкни меня! Публикация на MailMap');
    imageUrl = String(imageUrl || '');

    // Очистка от потенциальных символов, которые могут вызывать проблемы в URL
    // и применяем encodeURIComponent только к уже очищенным данным
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
                console.error('Неизвестная платформа:', platform);
                return;
        }

        // Открываем окно шеринга
        window.open(shareUrl, '_blank', 'width=600,height=400,resizable=yes,scrollbars=yes');

        // Для аналитики - можно добавить отслеживание событий шеринга
        console.log(`Поделились в ${platform}: ${url}`);
    } catch (e) {
        console.error('Ошибка при создании ссылки для шеринга:', e);
        alert('Не удалось поделиться. Пожалуйста, попробуйте позже.');
    }
}