// Globals
let currentDroppedFile = null;
let map;
let infoWindow;
let mapItems = []; // Stores the items to be displayed on the map
// Удалены: contextMenu, currentContextMenuLatLng
let addPhotoModal = null;
let currentPhotoAddLatLng = null; // Эта переменная используется в showAddPhotoModal и handlePhotoSubmit
let currentTargetItemId = null; // ID of the target post, if the map should center on it
let markers = {}; // Object to store markers by item ID

// Глобальные переменные для отслеживания долгого нажатия
let longPressTimer = null;
let pressStartTime = 0;
let pressStartLatLng = null;
let pressStartScreenCoords = null;
let isPointerCurrentlyDown = false;
let longPressActionTaken = false;

const LONG_PRESS_DURATION = 3000; // Длительность долгого нажатия в миллисекундах
const MOVE_THRESHOLD = 10;       // Порог смещения в пикселях

// Called by Google Maps API callback in index.html
function initMapCore() {
    const defaultLocation = { lat: 0, lng: 0 };
    map = new google.maps.Map(document.getElementById("map"), {
        zoom: 3,
        center: defaultLocation,
        mapId: "MAILMAP_DEMO_ID",
        mapTypeControl: true,
        streetViewControl: false,
        fullscreenControl: true,
        zoomControl: true,
        maxZoom: 20,
        gestureHandling: 'greedy'
    });
    infoWindow = new google.maps.InfoWindow();

    if (mapItems.length > 0) {
        populateMapWithMarkers();
    }

    // --- Логика долгого нажатия ---
    const handlePointerDown = (event) => {
        if (event.domEvent.type.startsWith('mouse') && event.domEvent.button !== 0) {
            return;
        }

        isPointerCurrentlyDown = true;
        longPressActionTaken = false;
        pressStartTime = Date.now();
        pressStartLatLng = event.latLng;

        if (event.domEvent.type.startsWith('touch')) {
            event.domEvent.preventDefault();
            pressStartScreenCoords = {
                clientX: event.domEvent.touches[0].clientX,
                clientY: event.domEvent.touches[0].clientY
            };
        } else { // Mouse event
            pressStartScreenCoords = {
                clientX: event.domEvent.clientX,
                clientY: event.domEvent.clientY
            };
        }

        clearTimeout(longPressTimer);
        longPressTimer = setTimeout(() => {
            if (isPointerCurrentlyDown) {
                console.log("Долгое нажатие для добавления фото в:", pressStartLatLng.toString());
                longPressActionTaken = true;
                // Сразу показываем модальное окно добавления фото
                showAddPhotoModal(pressStartLatLng);
            }
        }, LONG_PRESS_DURATION);
    };

    const handlePointerUp = (event) => {
        if (event.domEvent.type.startsWith('mouse') && event.domEvent.button !== 0) {
            return;
        }
        clearTimeout(longPressTimer);
        isPointerCurrentlyDown = false;
        // if (longPressActionTaken) {
        //     event.domEvent.preventDefault(); // Раскомментируйте, если модальное окно закрывается само
        // }
    };

    const handlePointerMove = (event) => {
        if (isPointerCurrentlyDown && pressStartScreenCoords) {
            let currentX, currentY;
            if (event.domEvent.type.startsWith('touch')) {
                if (!event.domEvent.touches || event.domEvent.touches.length === 0) return;
                currentX = event.domEvent.touches[0].clientX;
                currentY = event.domEvent.touches[0].clientY;
            } else { // Mouse event
                currentX = event.domEvent.clientX;
                currentY = event.domEvent.clientY;
            }

            const dx = Math.abs(currentX - pressStartScreenCoords.clientX);
            const dy = Math.abs(currentY - pressStartScreenCoords.clientY);

            if (dx > MOVE_THRESHOLD || dy > MOVE_THRESHOLD) {
                clearTimeout(longPressTimer);
            }
        }
    };

    google.maps.event.addListener(map, 'mousedown', handlePointerDown);
    google.maps.event.addListener(map, 'mouseup', handlePointerUp);
    google.maps.event.addListener(map, 'mousemove', handlePointerMove);

    map.getDiv().addEventListener('contextmenu', function(e) {
        if (longPressActionTaken) {
            e.preventDefault();
        }
    });

    // Глобальный слушатель клика для скрытия contextMenu удален, т.к. contextMenu больше нет

    // Add event listeners for drag and drop
    const mapDiv = map.getDiv();
    mapDiv.addEventListener('dragover', function(event) {
        event.preventDefault(); // Allow drop
    });

    mapDiv.addEventListener('drop', function(event) {
        event.preventDefault(); // Prevent browser's default file handling
        console.log('Drop event:', event);

        if (event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files.length > 0) {
            const file = event.dataTransfer.files[0];
            if (file.type.startsWith('image/')) {
                currentDroppedFile = file; // Store the file globally
                console.log('Image dropped:', currentDroppedFile.name);

                const mapContainer = map.getDiv();
                const mapRect = mapContainer.getBoundingClientRect();

                // Координаты мыши из события drop относительно окна браузера
                const clientX = event.clientX;
                const clientY = event.clientY;

                // Вычисляем пиксельные координаты (x, y) относительно левого верхнего угла контейнера карты
                const x = clientX - mapRect.left;
                const y = clientY - mapRect.top;

                // Проверяем, что точка отпускания находится внутри видимых границ контейнера карты
                if (x >= 0 && x <= mapRect.width && y >= 0 && y <= mapRect.height) {
                    const bounds = map.getBounds(); // Получаем текущие границы карты

                    if (bounds) {
                        const ne = bounds.getNorthEast(); // Северо-восточный угол
                        const sw = bounds.getSouthWest(); // Юго-западный угол
                        const span = bounds.toSpan();     // Объект LatLngSpan, представляющий "размах" границ

                        // Доля смещения по горизонтали (0.0 до 1.0)
                        const lngRatio = x / mapRect.width;
                        // Доля смещения по вертикали (0.0 до 1.0)
                        const latRatio = y / mapRect.height;

                        // Интерполируем долготу:
                        // Начинаем с юго-западной долготы и добавляем долю от общего пролета долгот
                        const lng = sw.lng() + span.lng() * lngRatio;

                        // Интерполируем широту:
                        // Начинаем с северо-восточной широты и вычитаем долю от общего пролета широт
                        // (потому что пиксельная координата Y растет вниз, а широта уменьшается)
                        const lat = ne.lat() - span.lat() * latRatio;

                        const latLng = new google.maps.LatLng(lat, lng);

                        console.log('Dropped photo location calculated (interpolation):', latLng.toString());
                        showAddPhotoModal(latLng); // Показываем модальное окно с этими координатами

                    } else {
                        alert('Map bounds are not available. Cannot determine drop location.');
                        currentDroppedFile = null; // Очищаем, если местоположение неизвестно
                    }
                } else {
                    console.warn('Drop detected, but calculated point is outside mapRect. ClientX/Y:', clientX, clientY, 'MapRect:', mapRect, 'Calculated x/y:', x, y);
                    alert('Dropped outside the map area or location could not be determined.');
                    currentDroppedFile = null;
                }
            } else {
                alert('Please drop an image file (e.g., JPG, PNG).');
                currentDroppedFile = null;
            }
        } else {
            currentDroppedFile = null;
        }
    });

    // --- Логика для вставки из буфера обмена (Paste) ---
    document.addEventListener('paste', function(event) {
        console.log('Paste event detected');
        const items = (event.clipboardData || event.originalEvent.clipboardData)?.items;
        if (!items) {
            console.log('Clipboard items not found.');
            return;
        }

        let imageFile = null;
        for (let i = 0; i < items.length; i++) {
            if (items[i].type.indexOf('image') !== -1) {
                imageFile = items[i].getAsFile();
                break;
            }
        }

        if (imageFile) {
            console.log('Image pasted:', imageFile.name);
            currentDroppedFile = imageFile; // Используем ту же переменную, что и для drag-n-drop

            // Определяем координаты для вставки.
            // Самый простой вариант - центр текущего вида карты.
            // Можно улучшить, если отслеживать последнее положение курсора на карте.
            const pasteLatLng = map.getCenter();

            if (pasteLatLng) {
                console.log('Using map center for pasted photo:', pasteLatLng.toString());
                showAddPhotoModal(pasteLatLng); // Показываем модальное окно
            } else {
                alert('Could not determine location for pasted image. Map center is not available.');
                currentDroppedFile = null; // Очищаем, если местоположение неизвестно
            }
            event.preventDefault(); // Предотвращаем стандартное действие вставки (если оно есть)
        } else {
            console.log('No image found in clipboard for pasting.');
        }
    });

}

// Функции showAddPhotoMenu и hideContextMenu удалены

// Ensure 'addPhotoModal' is declared at the top of map.js, e.g., let addPhotoModal = null;

async function showAddPhotoModal(latLng) {
    currentPhotoAddLatLng = latLng; // Set coordinates for form submission

    let fileInput; // Declare here to be accessible later
    let droppedFileInfo; // Declare here

    // --- Clipboard reading logic (remains unchanged) ---
    if (!currentDroppedFile && navigator.clipboard && typeof navigator.clipboard.read === 'function') {
        try {
            // ... (clipboard reading code as it is) ...
            console.log("Attempting to read image from clipboard...");
            const clipboardItems = await navigator.clipboard.read();
            for (const item of clipboardItems) {
                // Ищем первый элемент типа image
                const imageType = item.types.find(type => type.startsWith('image/'));
                if (imageType) {
                    const blob = await item.getType(imageType);
                    // Создаем объект File из Blob
                    const extension = imageType.split('/')[1] || 'png'; // Получаем расширение из MIME-типа
                    const fileName = `clipboard_image_${Date.now()}.${extension}`;
                    currentDroppedFile = new File([blob], fileName, {type: imageType});
                    console.log('Image taken from clipboard:', currentDroppedFile.name);
                    break; // Используем первое найденное изображение
                }
            }
        } catch (err) {
            // ... (error handling as it is) ...
            console.warn('Could not read image from clipboard (or no image found/permission denied):', err.name, err.message);
        }
    }
    // --- End of clipboard reading logic ---

    // Try to find the modal in the DOM first
    let modalElement = document.getElementById('add-photo-modal');

    if (!modalElement) {
        // If not found in DOM, create it
        console.log("#add-photo-modal not found in DOM. Creating it.");
        modalElement = document.createElement('div');
        modalElement.id = 'add-photo-modal';
        Object.assign(modalElement.style, {
            position: 'fixed', top: '0', left: '0', width: '100%', height: '100%',
            background: 'rgba(0,0,0,0.5)', display: 'flex', // Will be shown at the end
            alignItems: 'center', justifyContent: 'center', zIndex: '10001'
        });

        const modalContent = document.createElement('div');
        Object.assign(modalContent.style, {
            background: 'white', padding: '20px', borderRadius: '5px',
            boxShadow: '0 0 15px rgba(0,0,0,0.2)', textAlign: 'center', minWidth: '300px'
        });

        const title = document.createElement('h3');
        // Title will be set specifically for "Add Photo" later
        modalContent.appendChild(title);

        // Image preview (useful if openEditModal also uses this structure)
        let imagePreview = document.createElement('img');
        imagePreview.id = 'edit-image-preview'; // Keep consistent ID
        imagePreview.style.maxWidth = '100%';
        imagePreview.style.maxHeight = '200px';
        imagePreview.style.objectFit = 'contain';
        imagePreview.style.margin = '10px 0';
        imagePreview.style.display = 'none'; // Initially hidden
        modalContent.appendChild(imagePreview);

        droppedFileInfo = document.createElement('div');
        droppedFileInfo.id = 'dropped-file-info';
        droppedFileInfo.style.margin = '10px 0';
        droppedFileInfo.style.fontStyle = 'italic';
        modalContent.appendChild(droppedFileInfo);

        fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.accept = 'image/*';
        fileInput.id = 'photo-file-input';
        fileInput.style.margin = '10px 0';
        modalContent.appendChild(fileInput);

        const descriptionInput = document.createElement('textarea');
        descriptionInput.id = 'photo-description-input';
        descriptionInput.placeholder = 'Enter description';
        descriptionInput.style.margin = '10px 0';
        descriptionInput.style.width = 'calc(100% - 22px)'; // Adjusted for padding
        descriptionInput.rows = 3;
        modalContent.appendChild(descriptionInput);

        const buttonContainer = document.createElement('div');

        const submitButtonEl = document.createElement('button');
        // Text and listener will be set specifically for "Add Photo" later
        buttonContainer.appendChild(submitButtonEl);

        const cancelButtonEl = document.createElement('button');
        cancelButtonEl.textContent = 'Cancel';
        cancelButtonEl.style.marginLeft = '10px';
        cancelButtonEl.addEventListener('click', hideAddPhotoModal); // Directly use the robust hide function
        buttonContainer.appendChild(cancelButtonEl);

        modalContent.appendChild(buttonContainer);
        modalElement.appendChild(modalContent);
        document.body.appendChild(modalElement);
    }

    // At this point, modalElement is the correct DOM element (either found or created).
    // Update the global addPhotoModal variable in map.js to this element.
    // This assumes 'addPhotoModal' is a global variable in map.js scope
    addPhotoModal = modalElement; // Sync the global variable

    // Now, get references to internal elements from the definitive modalElement
    fileInput = addPhotoModal.querySelector('#photo-file-input'); // Re-assign from modalElement
    droppedFileInfo = addPhotoModal.querySelector('#dropped-file-info'); // Re-assign

    // Configure specifically for "Add Photo"
    const titleElement = addPhotoModal.querySelector('h3');
    if (titleElement) {
        titleElement.textContent = 'Add Photo';
    }

    // Ensure image preview is hidden for "Add Photo" unless a new image is being previewed
    // (which is not standard for this modal's add flow, it's for edit)
    const imagePreviewElement = addPhotoModal.querySelector('#edit-image-preview');
    if (imagePreviewElement) {
        imagePreviewElement.style.display = 'none';
        imagePreviewElement.src = '';
    }

    const submitButton = addPhotoModal.querySelector('button'); // First button
    if (submitButton) {
        // Clone and replace to remove old event listeners (e.g., from openEditModal)
        const newSubmitButton = submitButton.cloneNode(true);
        newSubmitButton.textContent = 'Submit';
        submitButton.parentNode.replaceChild(newSubmitButton, submitButton);
        newSubmitButton.addEventListener('click', handlePhotoSubmit); // Wire to ADD handler
    }

    if (currentDroppedFile) {
        if (droppedFileInfo) {
            droppedFileInfo.textContent = 'Using dropped file: ' + currentDroppedFile.name;
            droppedFileInfo.style.display = 'block';
        }
        if (fileInput) {
            fileInput.style.display = 'none';
            fileInput.value = '';
        }
    } else {
        if (droppedFileInfo) {
            droppedFileInfo.textContent = '';
            droppedFileInfo.style.display = 'none';
        }
        if (fileInput) {
            fileInput.style.display = 'block';
        }
    }

    addPhotoModal.style.display = 'flex'; // Show the modal
}

function hideAddPhotoModal() {
    currentDroppedFile = null; // Clear any globally stored dropped file related to adding photos

    const modalElement = document.getElementById('add-photo-modal');

    if (modalElement) {
        modalElement.style.display = 'none';

        // Also, update the global addPhotoModal variable in map.js if it was somehow
        // different or null, to keep it consistent if other parts of map.js rely on it.
        // However, direct manipulation via ID is now primary for hiding.
        if (typeof addPhotoModal !== 'undefined' && addPhotoModal !== modalElement) {
            // This line assumes 'addPhotoModal' is a global variable in map.js scope
            // If it's not declared with 'let' or 'var' at the top of map.js, this might cause issues
            // For now, let's assume it's a declared global within map.js
            // addPhotoModal = modalElement; // Optional: re-sync global map.js var
        }

        // Clear fields within the modal
        const fileInput = modalElement.querySelector('#photo-file-input');
        if (fileInput) {
            fileInput.value = ''; // Clear selected file
            fileInput.style.display = 'block'; // Ensure it's visible for next time (if it's an add modal)
        }

        const descriptionInput = modalElement.querySelector('#photo-description-input');
        if (descriptionInput) {
            descriptionInput.value = '';
        }

        const droppedFileInfo = modalElement.querySelector('#dropped-file-info');
        if (droppedFileInfo) {
            droppedFileInfo.textContent = '';
            droppedFileInfo.style.display = 'none';
        }

        // Reset title if it was changed (e.g. from "Edit Post" back to "Add Photo")
        // This is important if the same modal structure is reused.
        const titleElement = modalElement.querySelector('h3');
        if (titleElement) {
            // titleElement.textContent = 'Add Photo'; // Revert to default title
        }
        // Consider if the submit button text also needs resetting here if map.js's showAddPhotoModal expects it.
        // For now, openEditModal and showAddPhotoModal manage their own button text.

        console.log("Modal #add-photo-modal hidden and fields cleared by hideAddPhotoModal.");

    } else {
        console.error("hideAddPhotoModal called, but modal element with ID #add-photo-modal was not found in the DOM.");
    }
}

function updateMarkerInfoWindowContent(contentId, newText, newImageUrl) {
    console.log('Attempting to update info window for contentId:', contentId, 'with new text:', newText, 'and new image URL:', newImageUrl);

    const itemIndex = mapItems.findIndex(item => item.itemId === contentId);
    if (itemIndex === -1) {
        console.error('Item not found in mapItems:', contentId);
        return;
    }
    mapItems[itemIndex].text = newText;
    // Update imageUrl only if newImageUrl is explicitly provided.
    // This allows preserving it if not part of the update (e.g. text-only edit)
    // or clearing it if newImageUrl is null.
    if (newImageUrl !== undefined) {
        mapItems[itemIndex].imageUrl = newImageUrl;
    }
    console.log('Updated item data in mapItems:', mapItems[itemIndex]);

    const marker = markers[contentId];
    if (!marker) {
        console.error('Marker not found for contentId:', contentId);
    }

    if (infoWindow && infoWindow.getMap() && marker && infoWindow.anchor === marker) {
        const updatedItem = mapItems[itemIndex];
        const newInfoWindowContent = createInfoWindowContent(updatedItem);
        infoWindow.setContent(newInfoWindowContent);
        console.log('Updated content of currently open info window for', contentId);
    } else {
        console.log('Info window for', contentId, 'not currently open or currentInfoWindow is for another marker.');
    }
}

function handlePhotoSubmit() {
    const fileInput = document.getElementById('photo-file-input');
    const descriptionInput = document.getElementById('photo-description-input');
    // Use currentDroppedFile if available, otherwise use the file from input
    const file = currentDroppedFile || (fileInput ? fileInput.files[0] : null);
    const description = descriptionInput ? descriptionInput.value : '';

    if (!file) {
        alert('Please select a photo to upload.');
        return;
    }
    if (!currentPhotoAddLatLng) {
        alert('Error: Location not selected for photo. Please try again.');
        return;
    }

    if (typeof showLoading === 'function') showLoading(true);

    const formData = new FormData();
    formData.append('image', file);
    formData.append('text', description);
    formData.append('latitude', currentPhotoAddLatLng.lat());
    formData.append('longitude', currentPhotoAddLatLng.lng());
    formData.append('userId', (typeof currentUser !== 'undefined' && currentUser) ? currentUser.uid : 'anonymous');

    currentDroppedFile = null; // Clear the global reference to the dropped file

    fetch('/api/content/create', {
        method: 'POST',
        body: formData
    })
    .then(response => {
        if (typeof showLoading === 'function') showLoading(false);
        if (response.ok) {
            return response.json();
        } else {
            response.text().then(text => {
                alert('Error adding photo: ' + (text || response.statusText));
            }).catch(() => {
                alert('Error adding photo: ' + response.statusText);
            });
            throw new Error('Server responded with an error: ' + response.statusText);
        }
    })
    .then(newItemData => {
        if (newItemData && newItemData.content) {
            addItemToMap(newItemData.content);
        } else if (newItemData && newItemData.contentId) {
            console.warn("Photo added, but full item data not returned. addItemToMap might not work as expected.", newItemData);
            const tempItem = {
                itemId: newItemData.contentId,
                latitude: currentPhotoAddLatLng.lat(),
                longitude: currentPhotoAddLatLng.lng(),
                text: description,
                imageUrl: URL.createObjectURL(file),
                status: 'for_moderation',
                timestamp: new Date().toISOString()
            };
            addItemToMap(tempItem);
        }
        hideAddPhotoModal();
        alert('Photo added successfully! It will appear after moderation.');
    })
    .catch(error => {
        console.error('Error during photo submission:', error);
        if (typeof showLoading === 'function') showLoading(false);
        alert('Network error or server issue: ' + error.message);
    });
}

function setMapItemsAndPopulate(items, targetItemId) {
    mapItems = items || [];
    currentTargetItemId = targetItemId || null;

    if (typeof google !== 'undefined' && google.maps && map) {
        populateMapWithMarkers();
    }
}

function populateMapWithMarkers() {
    if (!map || !mapItems) {
        console.warn("Map or mapItems not ready for populating markers.");
        return;
    }
    clearAllMarkers();
    let mapCenter = { lat: 0, lng: 0 };
    let initialZoom = 3;

    if (mapItems && mapItems.length > 0) {
        if (mapItems.length === 1) {
            mapCenter = { lat: mapItems[0].latitude, lng: mapItems[0].longitude };
            initialZoom = 10;
        } else {
            const bounds = new google.maps.LatLngBounds();
            mapItems.forEach(item => {
                if (typeof item.latitude === 'number' && typeof item.longitude === 'number') {
                    bounds.extend({ lat: item.latitude, lng: item.longitude });
                }
            });
            if (!bounds.isEmpty()) {
                const center = bounds.getCenter();
                mapCenter = { lat: center.lat(), lng: center.lng() };
            } else {
                console.warn("No valid coordinates in mapItems to determine bounds.");
            }
        }
        map.setCenter(mapCenter);
        map.setZoom(initialZoom);
        if (mapItems.length > 1) {
            const bounds = new google.maps.LatLngBounds();
            let validItemsExist = false;
            mapItems.forEach(item => {
                if (typeof item.latitude === 'number' && typeof item.longitude === 'number') {
                    bounds.extend({ lat: item.latitude, lng: item.longitude });
                    validItemsExist = true;
                }
            });
            if (validItemsExist) {
                map.fitBounds(bounds);
            }
        }
    }
    addMarkersToMapInternal();
    if (currentTargetItemId) {
        focusOnTargetItem(currentTargetItemId);
    }
}

function clearAllMarkers() {
    for (const markerId in markers) {
        if (markers.hasOwnProperty(markerId)) {
            markers[markerId].map = null;
        }
    }
    markers = {};
}

function addMarkersToMapInternal() {
    if (!mapItems) return;
    mapItems.forEach(item => {
        if (typeof item.latitude === 'number' && typeof item.longitude === 'number' && item.itemId) {
            const marker = createMarker(item);
            markers[item.itemId] = marker;
        } else {
            console.warn("Skipping item due to invalid coordinates or missing itemId:", item);
        }
    });
}

function createMarker(item) {
    const markerPosition = { lat: item.latitude, lng: item.longitude };
    const isUnderModeration = item.status === 'for_moderation';

    const markerElement = document.createElement('div');
    markerElement.style.cursor = 'pointer';
    markerElement.className = 'custom-marker';

    if (isUnderModeration) {
        const moderationIndicator = document.createElement('div');
        Object.assign(moderationIndicator.style, {
            position: 'absolute', top: '-5px', right: '-5px', backgroundColor: '#FFC107',
            borderRadius: '50%', width: '20px', height: '20px', display: 'flex',
            alignItems: 'center', justifyContent: 'center', fontSize: '14px',
            fontWeight: 'bold', border: '2px solid white'
        });
        moderationIndicator.textContent = '!';
        markerElement.style.position = 'relative';
        markerElement.appendChild(moderationIndicator);
    }

    if (item.imageUrl) {
        const imgElement = document.createElement('img');
        imgElement.src = item.imageUrl;
        Object.assign(imgElement.style, {
            width: '60px', height: '60px', objectFit: 'cover', borderRadius: '8px',
            border: isUnderModeration ? '2px solid #FFC107' : '2px solid white',
            boxShadow: '0 2px 4px rgba(0,0,0,0.3)'
        });
        if (isUnderModeration) imgElement.style.filter = 'brightness(0.8)';
        markerElement.appendChild(imgElement);
    } else {
        const textElement = document.createElement('div');
        textElement.textContent = item.text?.substring(0, 10) || 'Post';
        Object.assign(textElement.style, {
            backgroundColor: isUnderModeration ? '#FFC107' : '#4285F4',
            color: isUnderModeration ? '#000' : 'white', padding: '8px',
            borderRadius: '8px', fontSize: '12px', fontWeight: 'bold',
            boxShadow: '0 2px 4px rgba(0,0,0,0.3)'
        });
        markerElement.appendChild(textElement);
    }

    const marker = new google.maps.marker.AdvancedMarkerView({
        map: map,
        position: markerPosition,
        content: markerElement,
        title: item.text
    });

    const infoWindowContent = createInfoWindowContent(item);

    marker.addListener("click", () => {
        infoWindow.setContent(infoWindowContent);
        infoWindow.open({ anchor: marker, map });
        if (window.history && window.history.pushState) {
            const newUrl = `/post/${item.itemId}`;
            window.history.pushState({ itemId: item.itemId }, '', newUrl);
        }
    });
    return marker;
}

function focusOnTargetItem(itemId) {
    if (!itemId || !map) return;
    const targetItem = mapItems.find(item => item.itemId === itemId);
    const marker = markers[itemId];
    if (targetItem && marker) {
        map.setCenter({ lat: targetItem.latitude, lng: targetItem.longitude });
        map.setZoom(15);
        const infoWindowContent = createInfoWindowContent(targetItem);
        infoWindow.setContent(infoWindowContent);
        infoWindow.open({ anchor: marker, map });
    }
}

function createInfoWindowContent(item) {
    const isUnderModeration = item.status === 'for_moderation';
    const shareUrl = `${window.location.origin}/post/${item.itemId}`;

    setTimeout(() => {
        document.querySelectorAll('.share-btn').forEach(btn => {
            const shareHandler = function(e) {
                e.preventDefault();
                e.stopPropagation();
                const platform = this.getAttribute('data-platform');
                const url = this.getAttribute('data-url');
                const text = decodeURIComponent(this.getAttribute('data-text'));
                const image = this.getAttribute('data-image');
                shareOnSocialMedia(platform, url, text, image, e);
            };
            const newBtn = btn.cloneNode(true);
            btn.parentNode.replaceChild(newBtn, btn);
            newBtn.addEventListener('click', shareHandler);
        });
    }, 100);

    let deleteButtonHtml = '';
    console.log("Checking delete button for item:", item.itemId);
    console.log("userIdFromServerSession:", userIdFromServerSession);
    console.log("item.userId:", item.userId);

    let editButtonHtml = '';
    if (userIdFromServerSession && item.userId && userIdFromServerSession === item.userId) {
        deleteButtonHtml = `
            <button title="Delete Post" class="delete-btn" onclick="deleteContent('${item.itemId}', event)" style="background:none;border:none;color:#dc3545;cursor:pointer;font-size:1.2em;padding:5px;margin-left:10px;">
                🗑️
            </button>
        `;
        editButtonHtml = `
            <button title="Edit Post" class="edit-btn" onclick="openEditModal('${item.itemId}')" style="background:none;border:none;color:#007bff;cursor:pointer;font-size:1.2em;padding:5px;margin-left:20px;">
                ✏️
            </button>
        `;
    }

    return `
        <div style="max-width:300px; padding-bottom: 10px;">
            ${isUnderModeration ? `<div style="background-color:#FFF3CD;color:#856404;padding:5px 10px;margin-bottom:5px;border-radius:4px;font-size:12px;border:1px solid #FFEEBA;">
                <strong>⚠️ Under Moderation</strong><br>
                This post is under review by a moderator.
            </div>` : ''}
            ${item.imageUrl ? `<img src="${item.imageUrl}" alt="${item.text || 'Image'}" style="width:100%;max-height:180px;object-fit:cover;margin-bottom:5px;border-radius:4px;cursor:pointer;" onclick="showFullSizeImage('${item.imageUrl}', event)">` : ''}
            <div class="vote-container" style="display:flex;align-items:center;margin-top: ${item.imageUrl ? '5px' : '0'}; margin-bottom:5px;">
                <span id="vote-count-${item.itemId}" style="margin-right:10px;font-size:12px;">Votes: ${item.voteCount || 0}</span>
                <button onclick="voteContent('${item.itemId}', 1, event)" class="vote-btn like-btn" style="background-color:#4CAF50;color:white;border:none;border-radius:4px;padding:4px 8px;margin-right:5px;cursor:pointer;${isUnderModeration ? 'opacity:0.5;' : ''}"${isUnderModeration ? ' disabled' : ''}>
                    <span style="font-size:12px;">👍</span>
                </button>
                <button onclick="voteContent('${item.itemId}', -1, event)" class="vote-btn dislike-btn" style="background-color:#f44336;color:white;border:none;border-radius:4px;padding:4px 8px;cursor:pointer;${isUnderModeration ? 'opacity:0.5;' : ''}"${isUnderModeration ? ' disabled' : ''}>
                    <span style="font-size:12px;">👎</span>
                </button>
            </div>
            <h3 style="margin-top:0;margin-bottom:4px;font-size:15px;">${item.text || 'Post without text'}</h3>
            <p style="font-size:11px;color:#666;margin:0;margin-bottom:5px;">${formatTimestamp(item.timestamp)}</p>
            
            <div style="margin-top:5px;border-top:1px solid #eee;padding-top:5px;">
                <div style="font-size:11px;color:#666;margin-bottom:4px;">Share:</div>
                <div style="display:flex;gap:5px;margin-bottom:5px;">
                    <button class="share-btn" data-platform="telegram" data-url="${shareUrl}" data-text="${item.text ? encodeURIComponent(item.text) : 'Like me! Post on MailMap'}" data-image="${item.imageUrl || ''}" style="background-color:#0088CC;color:white;border:none;border-radius:4px;padding:3px 6px;font-size:11px;cursor:pointer;">
                        Telegram
                    </button>
                    <button class="share-btn" data-platform="x" data-url="${shareUrl}" data-text="${item.text ? encodeURIComponent(item.text) : 'Like me! Post on MailMap'}" data-image="${item.imageUrl || ''}" style="background-color:#000000;color:white;border:none;border-radius:4px;padding:3px 6px;font-size:11px;cursor:pointer;">
                        X
                    </button>
                    <button class="share-btn" data-platform="whatsapp" data-url="${shareUrl}" data-text="${item.text ? encodeURIComponent(item.text) : 'Like me! Post on MailMap'}" data-image="${item.imageUrl || ''}" style="background-color:#25D366;color:white;border:none;border-radius:4px;padding:3px 6px;font-size:11px;cursor:pointer;">
                        WhatsApp
                    </button>
                </div>
                
                <div style="margin-bottom:5px;">
                    <button onclick="copyToClipboard('${shareUrl}')" style="background:none;border:none;color:#4285F4;font-size:11px;text-decoration:underline;cursor:pointer;padding:0;">
                        Copy link
                    </button>
                </div>

                <div style="display:flex;justify-content:space-between;align-items:center;margin-top:5px;">
                    <div>
                        ${editButtonHtml}
                        ${deleteButtonHtml}
                    </div>
                    ${!isUnderModeration ? `
                    <button onclick="reportContent('${item.itemId}', event)" class="report-btn" style="background:none;border:none;color:#999;font-size:11px;text-decoration:underline;cursor:pointer;padding:0;">
                        Report
                    </button>` : ''}
                </div>
            </div>
        </div>    
`;
}

function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        alert('Link copied to clipboard!');
    }).catch(err => {
        console.error('Failed to copy link: ', err);
    });
}

function showFullSizeImage(imageUrl, event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    const currentUrl = window.location.href;
    const modal = document.createElement('div');
    modal.className = 'image-modal';
    const sharingContainer = document.createElement('div');
    sharingContainer.className = 'sharing-buttons';
    sharingContainer.innerHTML = `
        <div style="background-color:rgba(0,0,0,0.7);padding:10px;border-radius:8px;position:absolute;bottom:20px;left:50%;transform:translateX(-50%);display:flex;gap:10px;">
            <button onclick="shareOnSocialMedia('vk', '${currentUrl}', 'Like me! Photo on MailMap', '${imageUrl}')"
                style="background-color:#4C75A3;color:white;border:none;border-radius:4px;padding:8px 12px;cursor:pointer;font-size:14px;">
                VK
            </button>
            <button onclick="shareOnSocialMedia('telegram', '${currentUrl}', 'Like me! Photo on MailMap', '${imageUrl}')"
                style="background-color:#0088CC;color:white;border:none;border-radius:4px;padding:8px 12px;cursor:pointer;font-size:14px;">
                Telegram
            </button>
            <button onclick="shareOnSocialMedia('whatsapp', '${currentUrl}', 'Like me! Photo on MailMap', '${imageUrl}')"
                style="background-color:#25D366;color:white;border:none;border-radius:4px;padding:8px 12px;cursor:pointer;font-size:14px;">
                WhatsApp
            </button>
            <button onclick="copyToClipboard('${currentUrl}')"
                style="background-color:#555;color:white;border:none;border-radius:4px;padding:8px 12px;cursor:pointer;font-size:14px;">
                Copy Link
            </button>
        </div>
    `;
    modal.style.position = 'fixed';
    modal.style.top = '0';
    modal.style.left = '0';
    modal.style.width = '100%';
    modal.style.height = '100%';
    modal.style.backgroundColor = 'rgba(0,0,0,0.9)';
    modal.style.display = 'flex';
    modal.style.justifyContent = 'center';
    modal.style.alignItems = 'center';
    modal.style.zIndex = '9999';
    const img = document.createElement('img');
    img.src = imageUrl;
    img.style.maxWidth = '90%';
    img.style.maxHeight = '90%';
    img.style.objectFit = 'contain';
    img.style.border = '2px solid white';
    img.style.borderRadius = '4px';
    img.style.boxShadow = '0 4px 8px rgba(0,0,0,0.5)';
    const closeBtn = document.createElement('button');
    closeBtn.textContent = '×';
    closeBtn.style.position = 'absolute';
    closeBtn.style.top = '20px';
    closeBtn.style.right = '20px';
    closeBtn.style.backgroundColor = 'transparent';
    closeBtn.style.border = 'none';
    closeBtn.style.color = 'white';
    closeBtn.style.fontSize = '30px';
    closeBtn.style.cursor = 'pointer';
    modal.addEventListener('click', function() {
        document.body.removeChild(modal);
    });
    img.addEventListener('click', function(e) {
        e.stopPropagation();
    });
    modal.appendChild(img);
    modal.appendChild(closeBtn);
    document.body.appendChild(modal);
}

function formatTimestamp(timestamp) {
    if (!timestamp) return new Date().toLocaleString();
    if (timestamp._seconds) {
        return new Date(timestamp._seconds * 1000).toLocaleString();
    } else if (timestamp.seconds) {
        return new Date(timestamp.seconds * 1000).toLocaleString();
    } else if (timestamp instanceof Date) {
        return timestamp.toLocaleString();
    } else if (typeof timestamp === 'string') {
        return new Date(timestamp).toLocaleString();
    }
    return new Date(timestamp).toLocaleString();
}

function addItemToMap(item) {
    if (!map) {
        console.error("Map not initialized. Cannot add item dynamically.");
        return;
    }
    if (!Array.isArray(mapItems)) {
        mapItems = [];
    }
    mapItems.push(item);
    if (typeof item.latitude === 'number' && typeof item.longitude === 'number' && item.itemId) {
        const marker = createMarker(item);
        markers[item.itemId] = marker;
    } else {
        console.warn("New item has invalid coordinates or missing itemId, not adding to map:", item);
    }
}

function updateItemVoteCount(itemId, newVoteCount) {
    const itemIndex = mapItems.findIndex(item => item.itemId === itemId);
    if (itemIndex !== -1) {
        mapItems[itemIndex].voteCount = newVoteCount;
        const voteCountElement = document.getElementById(`vote-count-${itemId}`);
        if (voteCountElement) voteCountElement.textContent = `Votes: ${newVoteCount}`;
    }
}

function removeMarkerFromMap(contentId) {
    const marker = markers[contentId];
    if (marker) {
        marker.map = null; // Remove from Google Map (AdvancedMarkerView)
        // For google.maps.Marker, it would be marker.setMap(null);
        delete markers[contentId]; // Remove from our tracking object
        console.log(`Marker ${contentId} removed from map.`);
    } else {
        console.warn(`Marker ${contentId} not found in markers object.`);
    }

    const itemIndex = mapItems.findIndex(item => item.itemId === contentId);
    if (itemIndex > -1) {
        mapItems.splice(itemIndex, 1);
        console.log(`Item ${contentId} removed from mapItems array.`);
    } else {
        console.warn(`Item ${contentId} not found in mapItems array.`);
    }

    // If the info window is open and showing the deleted item, close it.
    if (infoWindow && infoWindow.getMap()) {
        // Check if the content of the info window is for the deleted item.
        // This is a bit tricky as we don't directly store which item an info window is for.
        // A simple approach: if an item was deleted, and an info window is open,
        // it *might* be for this item. Closing it is a safe bet.
        // A more robust way would be to check if infoWindow.anchor === marker, but marker is already nullified.
        // Or, check if the infoWindow content contains the contentId.
        const currentInfoWindowContent = infoWindow.getContent();
        if (typeof currentInfoWindowContent === 'string' && currentInfoWindowContent.includes(contentId)) {
            infoWindow.close();
            console.log(`Closed info window that was displaying content for ${contentId}.`);
        }
    }
}