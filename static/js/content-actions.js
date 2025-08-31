// =============================================================================
// КОНСТАНТЫ И КОНФИГУРАЦИЯ
// =============================================================================

const CONFIG = {
    MAX_RETRIES: 3,
    REQUEST_TIMEOUT: 10000,
    MAX_TEXT_LENGTH: 500,
    MIN_REASON_LENGTH: 3,
    AUTH_MAX_RETRIES: 10,
    AUTH_DELAY: 500,
    EXPONENTIAL_BACKOFF_BASE: 1000
};

// =============================================================================
// УТИЛИТНЫЕ ФУНКЦИИ
// =============================================================================

// Утилитная функция для безопасного ожидания аутентификации
async function waitForAuth(maxRetries = CONFIG.AUTH_MAX_RETRIES, delay = CONFIG.AUTH_DELAY) {
    for (let i = 0; i < maxRetries; i++) {
        if (currentUser) return currentUser;
        await new Promise(resolve => setTimeout(resolve, delay));
    }
    throw new Error('Authentication timeout');
}

// Утилитная функция для безопасной очистки текста
function cleanForSharing(text) {
    return String(text || '')
        .replace(/[\"'`]/g, '')
        .replace(/[<>]/g, '')
        .replace(/[\r\n\t]/g, ' ')
        .trim()
        .substring(0, CONFIG.MAX_TEXT_LENGTH);
}

// Утилитная функция для валидации URL
function isValidUrl(string) {
    try {
        new URL(string);
        return true;
    } catch (_) {
        return false;
    }
}

// Утилитная функция для безопасного fetch с повторными попытками
async function safeFetch(url, options = {}, maxRetries = CONFIG.MAX_RETRIES) {
    for (let i = 0; i < maxRetries; i++) {
        try {
            const response = await fetch(url, {
                timeout: CONFIG.REQUEST_TIMEOUT,
                ...options
            });

            if (!response.ok) {
                let errorMsg = `HTTP error! status: ${response.status}`;
                try {
                    const errorData = await response.json();
                    errorMsg += `, Message: ${errorData.message || JSON.stringify(errorData)}`;
                } catch (e) {
                    // Ignore if response is not JSON
                }
                throw new Error(errorMsg);
            }

            // Check if the response is JSON before trying to parse it
            const contentType = response.headers.get("content-type");
            if (contentType && contentType.indexOf("application/json") !== -1) {
                return await response.json();
            } else {
                return await response.text();
            }
        } catch (error) {
            console.warn(`Attempt ${i + 1} failed:`, error.message);
            if (i === maxRetries - 1) throw error;
            await new Promise(resolve => setTimeout(resolve, CONFIG.EXPONENTIAL_BACKOFF_BASE * (i + 1)));
        }
    }
}

// Функция для показа/скрытия индикатора загрузки
function showLoading(isLoading) {
    let loadingOverlay = document.getElementById('loading-overlay');
    if (!loadingOverlay) {
        loadingOverlay = document.createElement('div');
        loadingOverlay.id = 'loading-overlay';
        Object.assign(loadingOverlay.style, {
            position: 'fixed',
            top: '0',
            left: '0',
            width: '100%',
            height: '100%',
            backgroundColor: 'rgba(0, 0, 0, 0.5)',
            color: 'white',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: '10002',
            fontSize: '20px'
        });
        loadingOverlay.textContent = 'Loading...';
        document.body.appendChild(loadingOverlay);
    }
    loadingOverlay.style.display = isLoading ? 'flex' : 'none';
}

// =============================================================================
// ФУНКЦИИ ВЗАИМОДЕЙСТВИЯ С КОНТЕНТОМ
// =============================================================================

// Улучшенная функция голосования
async function voteContent(contentId, voteValue, event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }

    try {
        await waitForAuth();

        if (!contentId || !voteValue) {
            throw new Error('Missing required parameters');
        }

        let btn = event?.target?.closest('.vote-btn');
        if (btn) {
            btn.disabled = true;
            btn.style.opacity = '0.5';
        }

        const data = await safeFetch(`/api/content/${contentId}/vote`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${currentUser.token || ''}`,
                'X-User-ID': currentUser.uid
            },
            body: JSON.stringify({
                vote: voteValue,
                userId: currentUser.uid
            })
        });

        if (data.status === 'success') {
            updateItemVoteCount(contentId, data.newVoteCount);

            if (btn) {
                btn.classList.add('voted');
                setTimeout(() => btn.classList.remove('voted'), 500);
            }
        } else {
            throw new Error(data.message || 'Vote failed');
        }

    } catch (error) {
        console.error('Vote error:', error);
        alert(`Ошибка голосования: ${error.message}`);
    } finally {
        let btn = event?.target?.closest('.vote-btn');
        if (btn) {
            btn.disabled = false;
            btn.style.opacity = '1';
        }
    }
}

// Улучшенная функция репорта
async function reportContent(contentId, event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }

    try {
        await waitForAuth();

        const reason = prompt('Укажите причину жалобы:');
        if (reason === null || reason.trim() === '') return;

        if (reason.length < CONFIG.MIN_REASON_LENGTH) {
            alert(`Причина должна содержать минимум ${CONFIG.MIN_REASON_LENGTH} символа`);
            return;
        }

        const data = await safeFetch(`/api/content/${contentId}/report`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${currentUser.token || ''}`,
                'X-User-ID': currentUser.uid
            },
            body: JSON.stringify({
                reason: reason.trim(),
                userId: currentUser.uid
            })
        });

        if (data.status === 'success') {
            alert('Спасибо! Ваша жалоба отправлена модераторам.');
        } else {
            throw new Error(data.message || 'Report failed');
        }

    } catch (error) {
        console.error('Report error:', error);
        alert(`Ошибка отправки жалобы: ${error.message}`);
    }
}

// =============================================================================
// ФУНКЦИИ ШАРИНГА
// =============================================================================

// Улучшенная функция шаринга
async function shareOnSocialMedia(platform, url, title, imageUrl, event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }

    try {
        url = String(url || window.location.href);
        title = cleanForSharing(title || 'Look what I found on MailMap!');
        imageUrl = String(imageUrl || '');

        // Проверяем поддержку Web Share API для нативного шаринга
        if (platform === 'native' && navigator.share) {
            try {
                await navigator.share({
                    title: title,
                    text: title,
                    url: url
                });
                console.log('Native share successful');
                return;
            } catch (shareError) {
                if (shareError.name === 'AbortError') {
                    console.log('User cancelled native share');
                    return;
                }
                console.warn('Native share failed, falling back:', shareError);
            }
        }

        // Генерируем URL для шаринга
        let shareUrl;
        switch(platform) {
            case 'vk':
                shareUrl = `https://vk.com/share.php?url=${encodeURIComponent(url)}&title=${encodeURIComponent(title)}&image=${encodeURIComponent(imageUrl)}`;
                break;
            case 'telegram':
                shareUrl = `https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(title)}`;
                break;
            case 'whatsapp':
                shareUrl = `https://api.whatsapp.com/send?text=${encodeURIComponent(title + ' ' + url)}`;
                break;
            case 'facebook':
                shareUrl = `https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(url)}`;
                break;
            case 'x':
                shareUrl = `https://x.com/intent/tweet?url=${encodeURIComponent(url)}&text=${encodeURIComponent(title)}`;
                break;
            case 'twitter':
                shareUrl = `https://twitter.com/intent/tweet?url=${encodeURIComponent(url)}&text=${encodeURIComponent(title)}`;
                break;
            default:
                throw new Error(`Неизвестная платформа: ${platform}`);
        }

        // Открываем popup для шаринга
        const popup = window.open(
            shareUrl,
            '_blank',
            'width=600,height=400,resizable=yes,scrollbars=yes,noopener=yes,noreferrer=yes'
        );

        if (popup) {
            console.log(`Successfully opened ${platform} share dialog`);
        }

    } catch (error) {
        console.error('Share error:', error);
        alert(`Ошибка шаринга: ${error.message}`);

        // Fallback: копируем основную ссылку
        if (navigator.clipboard && navigator.clipboard.writeText) {
            try {
                await navigator.clipboard.writeText(url);
                alert('Произошла ошибка. Основная ссылка скопирована в буфер обмена.');
            } catch (clipboardError) {
                console.error('Clipboard fallback failed:', clipboardError);
            }
        }
    }
}

// Функция для добавления нативной кнопки шаринга
function addNativeShareButton(container) {
    if (navigator.share) {
        const nativeBtn = document.createElement('button');
        nativeBtn.innerHTML = '📤 Поделиться';
        nativeBtn.className = 'native-share-btn';
        nativeBtn.onclick = (e) => shareOnSocialMedia('native', window.location.href, document.title, '', e);
        container.prepend(nativeBtn);
    }
}

// =============================================================================
// ФУНКЦИИ РЕДАКТИРОВАНИЯ И УДАЛЕНИЯ КОНТЕНТА
// =============================================================================

// Функция для открытия модального окна редактирования
async function openEditModal(contentId) {
    if (!contentId) {
        console.error('No contentId provided for editing.');
        return;
    }

    try {
        if (typeof showLoading === 'function') showLoading(true);

        // Получаем данные контента
        const postData = await safeFetch(`/api/content/${contentId}`);
        if (!postData || !postData.content) {
            throw new Error('Content not found or failed to fetch.');
        }
        const { text, imageUrl } = postData.content;
        console.log('Fetched post data for editing:', postData.content);

        // Находим или создаем модальное окно
        let modal = document.getElementById('add-photo-modal');
        let descriptionInput, fileInput, droppedFileInfo, titleElement, submitButton, cancelButton, imagePreview;

        if (!modal) {
            console.log('Modal #add-photo-modal not found. Creating basic structure.');
            modal = document.createElement('div');
            modal.id = 'add-photo-modal';
            Object.assign(modal.style, {
                position: 'fixed', top: '0', left: '0', width: '100%', height: '100%',
                background: 'rgba(0,0,0,0.5)', display: 'none',
                alignItems: 'center', justifyContent: 'center', zIndex: '10001'
            });

            const modalContent = document.createElement('div');
            Object.assign(modalContent.style, {
                background: 'white', padding: '20px', borderRadius: '5px',
                boxShadow: '0 0 15px rgba(0,0,0,0.2)', textAlign: 'center', minWidth: '300px'
            });

            titleElement = document.createElement('h3');
            modalContent.appendChild(titleElement);

            imagePreview = document.createElement('img');
            imagePreview.id = 'edit-image-preview';
            imagePreview.style.maxWidth = '100%';
            imagePreview.style.maxHeight = '200px';
            imagePreview.style.objectFit = 'contain';
            imagePreview.style.margin = '10px 0';
            imagePreview.style.display = 'none';
            modalContent.appendChild(imagePreview);

            droppedFileInfo = document.createElement('div');
            droppedFileInfo.id = 'dropped-file-info';
            droppedFileInfo.style.margin = '10px 0';
            droppedFileInfo.style.fontStyle = 'italic';
            droppedFileInfo.style.display = 'none';
            modalContent.appendChild(droppedFileInfo);

            fileInput = document.createElement('input');
            fileInput.type = 'file';
            fileInput.accept = 'image/*';
            fileInput.id = 'photo-file-input';
            fileInput.style.margin = '10px 0';
            fileInput.style.display = 'block';
            modalContent.appendChild(fileInput);

            descriptionInput = document.createElement('textarea');
            descriptionInput.id = 'photo-description-input';
            descriptionInput.placeholder = 'Enter description';
            descriptionInput.style.margin = '10px 0';
            descriptionInput.style.width = 'calc(100% - 22px)';
            descriptionInput.rows = 3;
            modalContent.appendChild(descriptionInput);

            const buttonContainer = document.createElement('div');
            submitButton = document.createElement('button');
            buttonContainer.appendChild(submitButton);

            cancelButton = document.createElement('button');
            cancelButton.textContent = 'Cancel';
            cancelButton.style.marginLeft = '10px';
            cancelButton.addEventListener('click', () => modal.style.display = 'none');
            buttonContainer.appendChild(cancelButton);

            modalContent.appendChild(buttonContainer);
            modal.appendChild(modalContent);
            document.body.appendChild(modal);
        } else {
            // Модальное окно существует, получаем его компоненты
            titleElement = modal.querySelector('h3');
            descriptionInput = document.getElementById('photo-description-input');
            const buttons = modal.querySelectorAll('button');
            submitButton = buttons[0];
            cancelButton = buttons[1];
            fileInput = document.getElementById('photo-file-input');
            droppedFileInfo = document.getElementById('dropped-file-info');
            imagePreview = modal.querySelector('#edit-image-preview');
        }

        // Настраиваем кнопку отмены
        if (cancelButton && typeof hideAddPhotoModal === 'function') {
            const newCancelButton = cancelButton.cloneNode(true);
            cancelButton.parentNode.replaceChild(newCancelButton, cancelButton);
            newCancelButton.addEventListener('click', hideAddPhotoModal);
            cancelButton = newCancelButton;
        } else if (cancelButton) {
            const newCancelButton = cancelButton.cloneNode(true);
            cancelButton.parentNode.replaceChild(newCancelButton, cancelButton);
            newCancelButton.addEventListener('click', () => modal.style.display = 'none');
            cancelButton = newCancelButton;
        }

        // Сбрасываем состояние модального окна
        if (fileInput) {
            fileInput.value = '';
            fileInput.style.display = 'block';
        }
        if (droppedFileInfo) {
            droppedFileInfo.textContent = '';
            droppedFileInfo.style.display = 'none';
        }
        if (descriptionInput) {
            descriptionInput.value = '';
        }

        // Создаем превью изображения если его нет
        if (!imagePreview && descriptionInput) {
            imagePreview = document.createElement('img');
            imagePreview.id = 'edit-image-preview';
            imagePreview.style.maxWidth = '100%';
            imagePreview.style.maxHeight = '200px';
            imagePreview.style.objectFit = 'contain';
            imagePreview.style.margin = '10px 0';
            descriptionInput.parentNode.insertBefore(imagePreview, descriptionInput);
        }

        // Заполняем модальное окно данными для редактирования
        if (titleElement) titleElement.textContent = 'Edit Post';
        if (descriptionInput) descriptionInput.value = text || '';

        if (imageUrl) {
            if (imagePreview) {
                imagePreview.src = imageUrl;
                imagePreview.style.display = 'block';
            }
            if (fileInput) fileInput.style.display = 'none';
        } else {
            if (imagePreview) imagePreview.style.display = 'none';
            if (fileInput) fileInput.style.display = 'block';
        }

        // Настраиваем кнопку сохранения
        if (submitButton) {
            const newSubmitButton = submitButton.cloneNode(true);
            newSubmitButton.textContent = 'Save Changes';
            submitButton.parentNode.replaceChild(newSubmitButton, submitButton);

            newSubmitButton.addEventListener('click', async function handleEditSubmit() {
                newSubmitButton.disabled = true;
                console.log(`Submitting edit for contentId: ${contentId}`);
                const updatedText = descriptionInput ? descriptionInput.value : text;

                try {
                    if (typeof showLoading === 'function') showLoading(true);
                    await safeFetch(`/api/content/${contentId}/edit`, {
                        method: 'PUT',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': `Bearer ${currentUser?.token || ''}`,
                            'X-User-ID': (typeof currentUser !== 'undefined' && currentUser) ? currentUser.uid : ''
                        },
                        body: JSON.stringify({
                            text: updatedText,
                            imageUrl: imageUrl
                        })
                    });
                    alert('Post updated successfully!');

                    if (typeof updateMarkerInfoWindowContent === 'function') {
                        updateMarkerInfoWindowContent(contentId, updatedText, imageUrl);
                    } else {
                        console.warn('updateMarkerInfoWindowContent function not found.');
                    }

                    const modalToHide = document.getElementById('add-photo-modal');
                    if (typeof hideAddPhotoModal === 'function') {
                        console.log("Calling hideAddPhotoModal() to close modal.");
                        hideAddPhotoModal();
                    } else if (modalToHide) {
                        console.log("Closing modal manually.");
                        modalToHide.style.display = 'none';
                    } else {
                        console.error("Modal element #add-photo-modal not found at the time of hiding.");
                    }
                } catch (err) {
                    console.error('Error updating post:', err);
                    alert(`Failed to update post: ${err.message}`);
                } finally {
                    if (typeof showLoading === 'function') showLoading(false);
                    newSubmitButton.disabled = false;
                }
            });
        }

        // Показываем модальное окно
        modal.style.display = 'flex';

    } catch (error) {
        console.error('Error opening edit modal:', error);
        alert(`Error: ${error.message}`);
    } finally {
        if (typeof showLoading === 'function') showLoading(false);
    }
}

// Улучшенная функция удаления контента
async function deleteContent(contentId, event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }

    if (!contentId) {
        console.error('No contentId provided for deletion.');
        return;
    }

    try {
        await waitForAuth();

        // Двойное подтверждение для критичной операции
        if (!confirm("Вы действительно хотите удалить этот пост?")) {
            return;
        }

        if (!confirm("Это действие нельзя отменить. Продолжить?")) {
            return;
        }

        if (typeof showLoading === 'function') showLoading(true);

        const data = await safeFetch(`/api/content/${contentId}/delete`, {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${currentUser?.token || ''}`,
                'X-User-ID': (typeof currentUser !== 'undefined' && currentUser) ? currentUser.uid : ''
            }
        });

        if (data.status === 'success' || typeof data === 'string') {
            console.log(`Content ${contentId} deleted successfully`);
            alert('Пост успешно удален.');

            // Удаляем маркер с карты
            try {
                if (typeof removeMarkerFromMap === 'function') {
                    removeMarkerFromMap(contentId);
                } else if (typeof removeMarker === 'function') {
                    removeMarker(contentId);
                }
            } catch (mapError) {
                console.warn('Map update failed:', mapError);
            }

            // Удаляем элемент из списка
            const itemElement = document.getElementById(`content-item-${contentId}`);
            if (itemElement) {
                itemElement.remove();
            }

            // Закрываем информационное окно если оно открыто
            if (typeof infoWindow !== 'undefined' && infoWindow && infoWindow.getMap() &&
                typeof markers !== 'undefined' && markers[contentId] && infoWindow.anchor === markers[contentId]) {
                infoWindow.close();
            }

            // Редирект на главную страницу
            setTimeout(() => {
                window.location.href = '/';
            }, 1000);

        } else {
            throw new Error(data.message || 'Delete failed');
        }

    } catch (error) {
        console.error('Delete error:', error);
        alert(`Ошибка удаления: ${error.message}`);
    } finally {
        if (typeof showLoading === 'function') showLoading(false);
    }
}

// =============================================================================
// ГЛОБАЛЬНАЯ ОБРАБОТКА ОШИБОК
// =============================================================================

// Глобальная обработка ошибок для неперехваченных промисов
window.addEventListener('unhandledrejection', function(event) {
    console.error('Unhandled promise rejection:', event.reason);
    // Здесь можно добавить отправку ошибок в систему мониторинга
});

// Экспорт функций для использования в других модулях (если используется модульная система)
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        waitForAuth,
        cleanForSharing,
        isValidUrl,
        safeFetch,
        showLoading,
        voteContent,
        reportContent,
        shareOnSocialMedia,
        addNativeShareButton,
        openEditModal,
        deleteContent
    };
}