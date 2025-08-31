// static/js/auth.js
document.addEventListener('DOMContentLoaded', function() {
    // Ensure the firebase object is available from the script in index.html
    if (typeof firebase === 'undefined' || typeof firebase.auth === 'undefined') {
        console.error('Firebase SDK not loaded or not initialized. Google Sign-In will not work.');
        return;
    }

    // Находим все ссылки выхода из системы и добавляем обработчик
    const logoutLinks = document.querySelectorAll('a[href="/logout"]');
    logoutLinks.forEach(link => {
        link.addEventListener('click', function(e) {
            // Выполняем выход из Firebase Auth
            if (firebase.auth().currentUser) {
                firebase.auth().signOut().then(() => {
                    console.log('User signed out from Firebase');
                }).catch((error) => {
                    console.error('Error signing out:', error);
                });
            }
        });
    });

    const auth = firebase.auth();
    const googleProvider = new firebase.auth.GoogleAuthProvider(); // Renamed for clarity
    const appleProvider = new firebase.auth.OAuthProvider('apple.com');

    function handleGoogleSignIn() {
        auth.signInWithPopup(googleProvider)
            .then((result) => {
                // This gives you a Google Access Token. You can use it to access the Google API.
                // const credential = result.credential;
                // const token = credential.accessToken;
                // The signed-in user info.
                // const user = result.user;

                // Get the ID token to send to the backend
                return result.user.getIdToken();
            })
            .then((idToken) => {
                // Send ID token to backend
                return fetch('/google_callback', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ idToken: idToken }),
                });
            })
            .then(response => {
                if (!response.ok) {
                    // Try to get error message from backend if available
                    return response.json().then(errData => {
                        throw new Error(errData.message || `Server error: ${response.status}`);
                    });
                }
                return response.json();
            })
            .then(data => {
                if (data.status === 'success' && data.redirect_url) {
                    window.location.href = data.redirect_url;
                } else {
                    console.error('Google Sign-In was not successful or redirect URL missing:', data.message);
                    alert('Google Sign-In failed: ' + (data.message || 'Unknown error.'));
                }
            })
            .catch((error) => {
                console.error('Error during Google Sign-In:', error);
                let errorMessage = error.message;
                // Firebase specific error codes for sign-in popup
                if (error.code === 'auth/popup-closed-by-user') {
                    errorMessage = 'Sign-in popup closed before completion.';
                } else if (error.code === 'auth/popup-blocked') {
                    errorMessage = 'Popup blocked by browser. Please allow popups for this site.';
                }
                alert('Google Sign-In Error: ' + errorMessage);
            });
    }

    // Attach to button on login page
    const googleSignInButtonLogin = document.getElementById('google-signin-button');
    if (googleSignInButtonLogin) {
        googleSignInButtonLogin.addEventListener('click', handleGoogleSignIn);
    }

    // Attach to button on register page
    const googleSignInButtonRegister = document.getElementById('google-signin-button-register');
    if (googleSignInButtonRegister) {
        googleSignInButtonRegister.addEventListener('click', handleGoogleSignIn);
    }

    // Apple Sign-In
    function handleAppleSignIn() {
        auth.signInWithPopup(appleProvider)
            .then((result) => {
                // Get the ID token to send to the backend
                return result.user.getIdToken();
            })
            .then((idToken) => {
                // Send ID token to backend
                return fetch('/apple_callback', { // New endpoint for Apple
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ idToken: idToken }),
                });
            })
            .then(response => {
                if (!response.ok) {
                    // Try to get error message from backend if available
                    return response.json().then(errData => {
                        throw new Error(errData.message || `Server error: ${response.status}`);
                    });
                }
                return response.json();
            })
            .then(data => {
                if (data.status === 'success' && data.redirect_url) {
                    window.location.href = data.redirect_url;
                } else {
                    console.error('Apple Sign-In was not successful or redirect URL missing:', data.message);
                    alert('Apple Sign-In failed: ' + (data.message || 'Unknown error.'));
                }
            })
            .catch((error) => {
                console.error('Error during Apple Sign-In:', error);
                let errorMessage = error.message;
                // Firebase specific error codes for sign-in popup
                if (error.code === 'auth/popup-closed-by-user') {
                    errorMessage = 'Sign-in popup closed before completion.';
                } else if (error.code === 'auth/popup-blocked') {
                    errorMessage = 'Popup blocked by browser. Please allow popups for this site.';
                } else if (error.code === 'auth/account-exists-with-different-credential') {
                    errorMessage = 'An account already exists with the same email address but different sign-in credentials. Try signing in using a provider associated with this email address.';
                }
                alert('Apple Sign-In Error: ' + errorMessage);
            });
    }

    const appleSignInButton = document.getElementById('apple-signin-button');
    if (appleSignInButton) {
        appleSignInButton.addEventListener('click', handleAppleSignIn);
    }

    // Email/Password Login Form Handling
    const loginForm = document.getElementById('login-form');
    if (loginForm) {
        loginForm.addEventListener('submit', function(event) {
            event.preventDefault(); // Prevent default form submission

            const email = document.getElementById('email').value;
            const password = document.getElementById('password').value;
            const errorMessageElement = document.getElementById('login-error-message');

            if (errorMessageElement) {
                errorMessageElement.textContent = ''; // Clear previous errors
            }

            if (!email || !password) {
                if (errorMessageElement) {
                    errorMessageElement.textContent = 'Please enter both email and password.';
                }
                return;
            }

            // Initialize Firebase Auth if not already done (it should be by google sign in part)
            // const auth = firebase.auth(); // auth is already defined above for Google Sign-In

            auth.signInWithEmailAndPassword(email, password)
                .then((userCredential) => {
                    // Signed in
                    // Check if email is verified
                    if (!userCredential.user.emailVerified) {
                        if (errorMessageElement) {
                            errorMessageElement.textContent = "Your email is not verified. Please check your inbox for a verification link.";
                        }
                        // Optionally, sign the user out if you don't want them to stay partially logged in on the client
                        // auth.signOut();
                        // Prevent further processing by throwing an error or returning a rejected promise
                        throw new Error("Email not verified.");
                    }
                    return userCredential.user.getIdToken();
                })
                .then((idToken) => {
                    // Send ID token to backend
                    return fetch('/login', { // Target our /login endpoint
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ idToken: idToken }),
                    });
                })
                .then(response => {
                    if (!response.ok) {
                        // Try to get error message from backend if available
                        return response.json().then(errData => {
                            throw new Error(errData.message || `Server error: ${response.status}`);
                        });
                    }
                    return response.json();
                })
                .then(data => {
                    if (data.status === 'success' && data.redirect_url) {
                        window.location.href = data.redirect_url;
                    } else {
                        console.error('Login was not successful or redirect URL missing:', data.message);
                        if (errorMessageElement) {
                            errorMessageElement.textContent = 'Login failed: ' + (data.message || 'Unknown error from server.');
                        }
                    }
                })
                .catch((error) => {
                    console.error('Error during email/password sign-in:', error);
                    if (errorMessageElement) {
                        // Display Firebase auth errors or custom backend errors
                        let displayMessage = error.message;
                        // Customize messages for common Firebase auth errors
                        if (error.message === "Email not verified.") { // Catch the custom error thrown above
                            displayMessage = "Your email is not verified. Please check your inbox for a verification link.";
                        } else if (error.code === 'auth/user-not-found' || error.code === 'auth/wrong-password' || error.code === 'auth/invalid-credential') {
                            displayMessage = 'Invalid email or password.';
                        } else if (error.code === 'auth/invalid-email') {
                            displayMessage = 'Please enter a valid email address.';
                        }
                        // Ensure errorMessageElement is referenced if it was declared outside this scope, or re-get it.
                        // Assuming errorMessageElement is accessible here from the outer scope.
                        if (errorMessageElement) { // Check again in case it wasn't set due to error path
                           errorMessageElement.textContent = displayMessage; // Removed 'Login error: ' prefix for this specific message.
                        } else {
                            // Fallback if the element isn't found, though it should be.
                            alert(displayMessage);
                        }
                    } else if (errorMessageElement) {
                         // General error if not one of the specific caught ones
                         errorMessageElement.textContent = 'Login error: ' + error.message;
                    }
                });
        });
    }
});
