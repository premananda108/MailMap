// Globals
let map;
let infoWindow;
let mapItems = []; // Stores the items to be displayed on the map
let currentTargetItemId = null; // ID of the target post, if the map should center on it
let markers = {}; // Object to store markers by item ID

// Called by Google Maps API callback in index.html
function initMapCore() {
    const defaultLocation = { lat: 0, lng: 0 }; // Default center if no items
    map = new google.maps.Map(document.getElementById("map"), {
        zoom: 3,
        center: defaultLocation,
        mapId: "MAILMAP_DEMO_ID", // Make sure this is your correct Map ID
        mapTypeControl: true,
        streetViewControl: false,
        fullscreenControl: true,
        zoomControl: true,
        maxZoom: 20
    });

    infoWindow = new google.maps.InfoWindow();

    // If data was already set by setMapItemsAndPopulate, draw markers now
    if (mapItems.length > 0) {
        populateMapWithMarkers();
    }
}

// Called from index.html after mapData is available
function setMapItemsAndPopulate(items, targetItemId) {
    mapItems = items || []; // Ensure mapItems is an array
    currentTargetItemId = targetItemId || null; // Set target item ID

    // If map object is already initialized by initMapCore, draw markers
    if (typeof google !== 'undefined' && google.maps && map) {
        populateMapWithMarkers();
    }
}

// This function now handles map centering/fitting and calls marker creation
function populateMapWithMarkers() {
    if (!map || !mapItems) {
        console.warn("Map or mapItems not ready for populating markers.");
        return;
    }

    // Clear existing markers if any
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
                // map.fitBounds(bounds) will be called after setting zoom and center if multiple items
            } else {
                // All items lack valid coordinates, use default or handle error
                console.warn("No valid coordinates in mapItems to determine bounds.");
            }
        }
        
        map.setCenter(mapCenter);
        map.setZoom(initialZoom);

        // Fit bounds if there are multiple items with valid coordinates
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
    
    addMarkersToMapInternal(); // Call the function that iterates and creates markers
    
    // If there is a target post, center the map on it and open InfoWindow
    if (currentTargetItemId) {
        focusOnTargetItem(currentTargetItemId);
    }
}

// Clear all existing markers from the map
function clearAllMarkers() {
    for (const markerId in markers) {
        if (markers.hasOwnProperty(markerId)) {
            markers[markerId].map = null; // Remove from map
        }
    }
    markers = {}; // Reset markers object
}

// Internal function to add markers to the map based on mapItems
function addMarkersToMapInternal() {
    if (!mapItems) return;
    mapItems.forEach(item => {
        // Ensure item has valid latitude and longitude before creating a marker
        if (typeof item.latitude === 'number' && typeof item.longitude === 'number' && item.itemId) {
            const marker = createMarker(item);
            markers[item.itemId] = marker; // Store marker reference
        } else {
            console.warn("Skipping item due to invalid coordinates or missing itemId:", item);
        }
    });
}

// Function to create a single marker (structure based on your existing code)
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
        
        // Update URL to enable direct linking to this marker
        if (window.history && window.history.pushState) {
            const newUrl = `/post/${item.itemId}`;
            window.history.pushState({ itemId: item.itemId }, '', newUrl);
        }
    });

    return marker;
}

// Function to focus on a target item by ID
function focusOnTargetItem(itemId) {
    if (!itemId || !map) return;
    
    const targetItem = mapItems.find(item => item.itemId === itemId);
    const marker = markers[itemId];
    
    if (targetItem && marker) {
        // Center the map on the post
        map.setCenter({ lat: targetItem.latitude, lng: targetItem.longitude });
        map.setZoom(15); // Increase zoom for better visibility
        
        // Open info window
        const infoWindowContent = createInfoWindowContent(targetItem);
        infoWindow.setContent(infoWindowContent);
        infoWindow.open({ anchor: marker, map });
    }
}

// Function to create info window content (structure based on your existing code)
function createInfoWindowContent(item) {
    const isUnderModeration = item.status === 'for_moderation';
    const shareUrl = `${window.location.origin}/post/${item.itemId}`;

    // Add event delegation for share buttons
    setTimeout(() => {
        document.querySelectorAll('.share-btn').forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                const platform = this.getAttribute('data-platform');
                const url = this.getAttribute('data-url');
                const text = decodeURIComponent(this.getAttribute('data-text'));
                const image = this.getAttribute('data-image');
                shareOnSocialMedia(platform, url, text, image);
            });
        });
    }, 100);
    
    return `
        <div style="max-width:300px;">
            ${isUnderModeration ? `<div style="background-color:#FFF3CD;color:#856404;padding:5px 10px;margin-bottom:10px;border-radius:4px;font-size:12px;border:1px solid #FFEEBA;">
                <strong>⚠️ Under Moderation</strong><br>
                This post is under review by a moderator.
            </div>` : ''}
            ${item.imageUrl ? `<img src="${item.imageUrl}" alt="${item.text || 'Image'}" style="width:100%;max-height:200px;object-fit:cover;margin-bottom:8px;border-radius:4px;cursor:pointer;" onclick="showFullSizeImage('${item.imageUrl}', event)">` : ''}
            <div class="vote-container" style="display:flex;align-items:center;margin-top: ${item.imageUrl ? '8px' : '0'}; margin-bottom:10px;">
                <span id="vote-count-${item.itemId}" style="margin-right:10px;">Votes: ${item.voteCount || 0}</span>
                <button onclick="voteContent('${item.itemId}', 1, event)" class="vote-btn like-btn" style="background-color:#4CAF50;color:white;border:none;border-radius:4px;padding:5px 10px;margin-right:5px;cursor:pointer;${isUnderModeration ? 'opacity:0.5;' : ''}"${isUnderModeration ? ' disabled' : ''}>
                    <span style="font-size:14px;">👍</span>
                </button>
                <button onclick="voteContent('${item.itemId}', -1, event)" class="vote-btn dislike-btn" style="background-color:#f44336;color:white;border:none;border-radius:4px;padding:5px 10px;cursor:pointer;${isUnderModeration ? 'opacity:0.5;' : ''}"${isUnderModeration ? ' disabled' : ''}>
                    <span style="font-size:14px;">👎</span>
                </button>
            </div>
            <h3 style="margin-top:0;margin-bottom:8px;">${item.text || 'Post without text'}</h3>
            <p style="font-size:12px;color:#666;margin:0;margin-bottom:8px;">${formatTimestamp(item.timestamp)}</p>
            
            <!-- Share buttons -->
            <div style="margin-top:10px;border-top:1px solid #eee;padding-top:10px;">
                <div style="font-size:12px;color:#666;margin-bottom:5px;">Share:</div>
                <div style="display:flex;gap:8px;">
                    <button class="share-btn" data-platform="telegram" data-url="${shareUrl}" data-text="${item.text ? encodeURIComponent(item.text) : 'Like me! Post on MailMap'}" data-image="${item.imageUrl || ''}" style="background-color:#0088CC;color:white;border:none;border-radius:4px;padding:4px 8px;font-size:12px;cursor:pointer;">
                        Telegram
                    </button>
                    <button class="share-btn" data-platform="x" data-url="${shareUrl}" data-text="${item.text ? encodeURIComponent(item.text) : 'Like me! Post on MailMap'}" data-image="${item.imageUrl || ''}" style="background-color:#000000;color:white;border:none;border-radius:4px;padding:4px 8px;font-size:12px;cursor:pointer;">
                        X
                    </button>
                    <button class="share-btn" data-platform="whatsapp" data-url="${shareUrl}" data-text="${item.text ? encodeURIComponent(item.text) : 'Like me! Post on MailMap'}" data-image="${item.imageUrl || ''}" style="background-color:#25D366;color:white;border:none;border-radius:4px;padding:4px 8px;font-size:12px;cursor:pointer;">
                        WhatsApp
                    </button>
                </div>
            </div>

            <!-- Additional actions -->
            <div style="display:flex;justify-content:space-between;margin-top:10px;">
                <button onclick="copyToClipboard('${shareUrl}')" style="background:none;border:none;color:#4285F4;font-size:12px;text-decoration:underline;cursor:pointer;padding:0;">
                    Copy link
                </button>
                ${!isUnderModeration ? `
                <button onclick="reportContent('${item.itemId}', event)" class="report-btn" style="background:none;border:none;color:#999;font-size:12px;text-decoration:underline;cursor:pointer;padding:0;">
                    Report
                </button>` : ''}
            </div>
        </div>
    `;
}

// Function to copy URL to clipboard
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        alert('Link copied to clipboard!');
    }).catch(err => {
        console.error('Failed to copy link: ', err);
    });
}

// Function to show full-size image in a modal
function showFullSizeImage(imageUrl, event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }

    // Get current URL for sharing
    const currentUrl = window.location.href;

    // Create modal container
    const modal = document.createElement('div');
    modal.className = 'image-modal';

    // Add sharing buttons container
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

    // Create image element
    const img = document.createElement('img');
    img.src = imageUrl;
    img.style.maxWidth = '90%';
    img.style.maxHeight = '90%';
    img.style.objectFit = 'contain';
    img.style.border = '2px solid white';
    img.style.borderRadius = '4px';
    img.style.boxShadow = '0 4px 8px rgba(0,0,0,0.5)';

    // Close button
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

    // Add click event to close modal
    modal.addEventListener('click', function() {
        document.body.removeChild(modal);
    });

    // Prevent clicks on image from closing modal
    img.addEventListener('click', function(e) {
        e.stopPropagation();
    });

    // Append elements
    modal.appendChild(img);
    modal.appendChild(closeBtn);
    document.body.appendChild(modal);
}

// Function to format timestamp (structure based on your existing code)
function formatTimestamp(timestamp) {
    if (!timestamp) return new Date().toLocaleString();
    if (timestamp._seconds) { // Firestore Timestamp object
        return new Date(timestamp._seconds * 1000).toLocaleString();
    } else if (timestamp.seconds) { // Another Firestore Timestamp variant
        return new Date(timestamp.seconds * 1000).toLocaleString();
    } else if (timestamp instanceof Date) {
        return timestamp.toLocaleString();
    } else if (typeof timestamp === 'string') { // ISO string from server
        return new Date(timestamp).toLocaleString();
    }
    return new Date(timestamp).toLocaleString(); // Fallback
}

// Add a new item to the map (e.g., after user submits new content)
function addItemToMap(item) {
    if (!map) {
        console.error("Map not initialized. Cannot add item dynamically.");
        return;
    }
    // Ensure mapItems is an array before pushing
    if (!Array.isArray(mapItems)) {
        mapItems = [];
    }
    mapItems.push(item); // Add to the local JS array
    if (typeof item.latitude === 'number' && typeof item.longitude === 'number' && item.itemId) {
        const marker = createMarker(item);
        markers[item.itemId] = marker; // Store marker reference
    } else {
        console.warn("New item has invalid coordinates or missing itemId, not adding to map:", item);
    }
}

// Update vote count for an item on the map (structure based on your existing code)
function updateItemVoteCount(itemId, newVoteCount) {
    const itemIndex = mapItems.findIndex(item => item.itemId === itemId);
    if (itemIndex !== -1) {
        mapItems[itemIndex].voteCount = newVoteCount;
        const voteCountElement = document.getElementById(`vote-count-${itemId}`);
        if (voteCountElement) voteCountElement.textContent = `Votes: ${newVoteCount}`;
    }
}