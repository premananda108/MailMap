const firebaseConfig = {
    apiKey: "AIzaSyBZ32SzxLKcToP7CzD_SWMpJZpDAkzlScc",
    authDomain: "mailmap-de0bc.firebaseapp.com",
    projectId: "mailmap-de0bc",
    storageBucket: "mailmap-de0bc.firebasestorage.app",
    messagingSenderId: "724461961525",
    appId: "1:724461961525:web:0e476d7c653188c143cc7c",
    measurementId: "G-W3SNS81PKW"
};

if (!firebase.apps.length) {
    firebase.initializeApp(firebaseConfig);
} else {
    firebase.app(); // if already initialized, use that one
}
