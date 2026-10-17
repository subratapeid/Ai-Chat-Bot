
"use strict";

const chatForm = document.getElementById("chat-form");
const messageInput = document.getElementById("message-input");
const sendButton = document.getElementById("send-button");
const messagesElement = document.getElementById("messages");
const welcomeScreen = document.getElementById("welcome-screen");
const chatScroll = document.getElementById("chat-scroll");
const typingSlot = document.getElementById("typing-slot");
const connectionStatus = document.getElementById("connection-status");

const imageInput = document.getElementById("image-input");
const attachImageButton = document.getElementById("attach-image");
const attachmentPreview = document.getElementById("attachment-preview");
const attachmentPreviewImage = document.getElementById("attachment-preview-image");
const attachmentName = document.getElementById("attachment-name");
const attachmentSize = document.getElementById("attachment-size");
const removeAttachmentButton = document.getElementById("remove-attachment");

const sidebar = document.getElementById("sidebar");
const mobileOverlay = document.getElementById("mobile-overlay");

const profileNameElement = document.getElementById("profile-name");
const profileAvatarElement = document.getElementById("profile-avatar");
const profileSubtitleElement = document.getElementById("profile-subtitle");
const profileBadgeElement = document.getElementById("profile-badge");

const MAX_IMAGE_SIZE = 3 * 1024 * 1024;
const ALLOWED_IMAGE_TYPES = [
    "image/jpeg",
    "image/png",
    "image/webp"
];

const MAX_CONTEXT_MESSAGES = 12;

let messages = [];
let selectedImage = null;
let isSending = false;

/*
|--------------------------------------------------------------------------
| Guest profile
|--------------------------------------------------------------------------
*/

function loadGuestProfile() {
    let savedName = "";

    try {
        savedName = localStorage.getItem("proloy_guest_name") || "";
    } catch {
        // The application remains usable when browser storage is unavailable.
    }

    updateGuestProfile(savedName, false);
}

function updateGuestProfile(name, persist = true) {
    const cleanName = String(name || "").trim().slice(0, 60);
    const displayName = cleanName || "Guest";

    profileNameElement.textContent = displayName;
    profileAvatarElement.textContent = displayName.charAt(0).toUpperCase();
    profileSubtitleElement.textContent = cleanName
        ? "Guest profile"
        : "Local AI workspace";
    profileBadgeElement.textContent = "GUEST";

    if (!persist) {
        return;
    }

    try {
        if (cleanName) {
            localStorage.setItem("proloy_guest_name", cleanName);
        } else {
            localStorage.removeItem("proloy_guest_name");
        }
    } catch {
        // Ignore storage restrictions.
    }
}

function detectGuestName(text) {
    const patterns = [
        /\bmy name is\s+([a-z][a-z .'-]{0,58})/i,
        /\bcall me\s+([a-z][a-z .'-]{0,58})/i,
        /\bi am\s+([a-z][a-z .'-]{0,58})/i,
        /\bi'm\s+([a-z][a-z .'-]{0,58})/i
    ];

    const excludedStarts = /^(happy|looking|interested|trying|working|asking|calling|going|just|not|here|from|at|a|an|the|fine|good|doing|feeling|having|thinking|planning|wondering|sorry|unable|unable|available|new|currently|based|located|using|building|developing|learning|searching|waiting|ready|busy|okay|ok|sure|glad|excited|confused|tired|hungry|sad|great|curious|afraid|concerned|married|single|a developer|a student|a customer)\b/i;

    for (const pattern of patterns) {
        const match = text.match(pattern);

        if (!match) {
            continue;
        }

        const name = match[1]
            .replace(/[.!?,;:]+$/, "")
            .trim();

        if (
            !name ||
            name.split(/\s+/).length > 4 ||
            excludedStarts.test(name)
        ) {
            continue;
        }

        updateGuestProfile(name);
        return;
    }
}

/*
|--------------------------------------------------------------------------
| Connection status
|--------------------------------------------------------------------------
*/

function setConnectionStatus(text, online = null) {
    connectionStatus.textContent = text;

    const dot = document.querySelector(".header-status .status-dot");

    if (!dot) {
        return;
    }

    if (online === false) {
        dot.style.background = "#e59b62";
    } else if (online === true) {
        dot.style.background = "#31b881";
    } else {
        dot.style.background = "#aaa8ba";
    }
}

async function checkHealth() {
    try {
        const response = await fetch("/api/health");

        if (!response.ok) {
            throw new Error("Health check failed");
        }

        const data = await response.json();

        setConnectionStatus(
            data.status === "ok"
                ? "Local AI service ready"
                : "Checking local AI...",
            data.status === "ok"
        );
    } catch {
        setConnectionStatus("AI service unavailable", false);
    }
}

/*
|--------------------------------------------------------------------------
| Message rendering
|--------------------------------------------------------------------------
*/

function scrollToBottom() {
    requestAnimationFrame(() => {
        chatScroll.scrollTop = chatScroll.scrollHeight;
    });
}

function createAvatar(isAssistant) {
    const avatar = document.createElement("div");

    avatar.className = isAssistant
        ? "message-avatar assistant-avatar"
        : "message-avatar user-avatar";

    avatar.textContent = isAssistant
        ? "✦"
        : profileAvatarElement.textContent || "G";

    avatar.setAttribute(
        "aria-label",
        isAssistant ? "Proloy avatar" : "Your avatar"
    );

    return avatar;
}

function addImagesToMessage(container, images) {
    if (!Array.isArray(images) || images.length === 0) {
        return;
    }

    const imageGroup = document.createElement("div");
    imageGroup.className = "message-images";

    for (const image of images) {
        if (!image.dataUrl) {
            continue;
        }

        const img = document.createElement("img");

        img.className = "message-image";
        img.alt = image.name || "Attached image";
        img.loading = "lazy";
        img.src = image.dataUrl;

        imageGroup.appendChild(img);
    }

    if (imageGroup.childElementCount > 0) {
        container.appendChild(imageGroup);
    }
}

function renderMessage(message) {
    const isAssistant = message.role === "assistant";

    const row = document.createElement("article");

    row.className = [
        "message-row",
        isAssistant ? "assistant-message" : "user-message",
        message.error ? "message-error" : ""
    ].filter(Boolean).join(" ");

    row.appendChild(createAvatar(isAssistant));

    const body = document.createElement("div");
    body.className = "message-body";

    const heading = document.createElement("div");
    heading.className = "message-heading";

    const name = document.createElement("strong");
    name.textContent = isAssistant
        ? "Proloy"
        : profileNameElement.textContent || "Guest";

    const time = document.createElement("span");
    time.textContent = message.time || "Just now";

    heading.append(name, time);
    body.appendChild(heading);

    addImagesToMessage(body, message.images);

    if (message.content) {
        const content = document.createElement("div");
        content.className = "message-content";
        content.textContent = message.content;
        body.appendChild(content);
    }

    row.appendChild(body);
    messagesElement.appendChild(row);
}

function renderAllMessages() {
    messagesElement.replaceChildren();

    for (const message of messages) {
        renderMessage(message);
    }

    welcomeScreen.hidden = messages.length > 0;

    scrollToBottom();
}

/*
|--------------------------------------------------------------------------
| Typing animation
|--------------------------------------------------------------------------
*/

function showTyping() {
    typingSlot.replaceChildren();

    const row = document.createElement("div");

    row.className = "typing-row";
    row.setAttribute("role", "status");
    row.setAttribute("aria-label", "Proloy is typing");

    row.appendChild(createAvatar(true));

    const body = document.createElement("div");
    body.className = "typing-body";

    const heading = document.createElement("div");
    heading.className = "typing-heading";

    const name = document.createElement("strong");
    name.textContent = "Proloy";

    const status = document.createElement("span");
    status.textContent = "Thinking";

    heading.append(name, status);

    const bubble = document.createElement("div");
    bubble.className = "typing-bubble";
    bubble.setAttribute("aria-hidden", "true");

    for (let i = 0; i < 3; i++) {
        bubble.appendChild(document.createElement("span"));
    }

    body.append(heading, bubble);
    row.appendChild(body);
    typingSlot.appendChild(row);

    scrollToBottom();
}

function hideTyping() {
    typingSlot.replaceChildren();
}

/*
|--------------------------------------------------------------------------
| Image attachments
|--------------------------------------------------------------------------
*/

function formatSize(bytes) {
    return bytes < 1024 * 1024
        ? `${Math.max(1, Math.round(bytes / 1024))} KB`
        : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fileToDataUrl(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();

        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(
            new Error("Unable to read the selected image.")
        );

        reader.readAsDataURL(file);
    });
}

function clearAttachment() {
    selectedImage = null;
    imageInput.value = "";
    attachmentPreview.hidden = true;
    attachmentPreviewImage.removeAttribute("src");
    attachmentName.textContent = "";
    attachmentSize.textContent = "";
}

async function handleImageSelection(file) {
    if (!file) {
        return;
    }

    if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
        alert("Please select a PNG, JPG, or WebP image.");
        imageInput.value = "";
        return;
    }

    if (file.size > MAX_IMAGE_SIZE) {
        alert("Please select an image smaller than 3 MB.");
        imageInput.value = "";
        return;
    }

    try {
        const dataUrl = await fileToDataUrl(file);
        const separatorIndex = dataUrl.indexOf(",");

        if (separatorIndex < 0) {
            throw new Error("The selected image could not be prepared.");
        }

        const base64 = dataUrl.slice(separatorIndex + 1);

        selectedImage = {
            name: file.name,
            type: file.type,
            size: file.size,
            dataUrl,
            base64
        };

        attachmentPreviewImage.src = dataUrl;
        attachmentName.textContent = file.name;
        attachmentSize.textContent =
            `${formatSize(file.size)} · Ready to send`;

        attachmentPreview.hidden = false;
        messageInput.focus();
    } catch (error) {
        alert(error.message || "Unable to load the image.");
        clearAttachment();
    }
}

attachImageButton.addEventListener("click", () => {
    if (!isSending) {
        imageInput.click();
    }
});

imageInput.addEventListener("change", async () => {
    const file = imageInput.files && imageInput.files[0];
    await handleImageSelection(file);
});

removeAttachmentButton.addEventListener("click", clearAttachment);

/*
|--------------------------------------------------------------------------
| Prepare API conversation
|--------------------------------------------------------------------------
*/

function buildApiMessages() {
    const recentMessages = messages.slice(-MAX_CONTEXT_MESSAGES);

    const imageMessageIndexes = recentMessages
        .map((message, index) =>
            message.images && message.images.length ? index : -1
        )
        .filter(index => index !== -1);

    // Retain only the two most recent image messages in model context.
    const allowedImageIndexes = new Set(imageMessageIndexes.slice(-2));

    return recentMessages.map((message, index) => {
        const apiMessage = {
            role: message.role,
            content: message.content || ""
        };

        if (
            message.role === "user" &&
            message.images &&
            message.images.length &&
            allowedImageIndexes.has(index)
        ) {
            apiMessage.images = message.images
                .map(image => image.base64)
                .filter(Boolean)
                .slice(0, 1);
        }

        return apiMessage;
    });
}

/*
|--------------------------------------------------------------------------
| Sending messages
|--------------------------------------------------------------------------
*/

function setSendingState(sending) {
    isSending = sending;

    sendButton.disabled = sending;
    attachImageButton.disabled = sending;
    messageInput.disabled = sending;

    sendButton.classList.toggle("is-loading", sending);

    sendButton.setAttribute(
        "aria-label",
        sending ? "Proloy is responding" : "Send message"
    );
}

function resizeTextarea() {
    messageInput.style.height = "auto";

    messageInput.style.height =
        `${Math.min(messageInput.scrollHeight, 150)}px`;
}

async function sendMessage(textOverride = null) {
    if (isSending) {
        return;
    }

    const text = (
        textOverride !== null
            ? textOverride
            : messageInput.value
    ).trim();

    const image = selectedImage;

    if (!text && !image) {
        return;
    }

    detectGuestName(text);

    const messageText = text ||
        "Please describe and analyse this image.";

    const userMessage = {
        role: "user",
        content: messageText,
        time: "Just now",
        images: image
            ? [{
                name: image.name,
                type: image.type,
                size: image.size,
                dataUrl: image.dataUrl,
                base64: image.base64
            }]
            : []
    };

    messages.push(userMessage);

    messageInput.value = "";
    resizeTextarea();
    clearAttachment();

    renderAllMessages();
    setSendingState(true);
    showTyping();

    setConnectionStatus("Proloy is responding...", true);

    try {
        const response = await fetch("/api/chat", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                messages: buildApiMessages()
            })
        });

        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            throw new Error(
                data.error || `Request failed (${response.status}).`
            );
        }

        messages.push({
            role: "assistant",
            content: data.reply ||
                "I couldn't generate a response. Please try again.",
            time: "Just now",
            images: []
        });

        setConnectionStatus("Local AI service ready", true);
    } catch (error) {
        messages.push({
            role: "assistant",
            content: error.message ||
                "Unable to connect to the AI service. Check that Ollama is running.",
            time: "Just now",
            images: [],
            error: true
        });

        setConnectionStatus("AI service needs attention", false);
    } finally {
        hideTyping();
        setSendingState(false);
        renderAllMessages();
        messageInput.focus();
    }
}

chatForm.addEventListener("submit", event => {
    event.preventDefault();
    sendMessage();
});

messageInput.addEventListener("input", resizeTextarea);

messageInput.addEventListener("keydown", event => {
    if (
        event.key === "Enter" &&
        !event.shiftKey &&
        !event.isComposing
    ) {
        event.preventDefault();
        sendMessage();
    }
});

/*
|--------------------------------------------------------------------------
| Suggested prompts
|--------------------------------------------------------------------------
*/

document.querySelectorAll("[data-prompt]").forEach(button => {
    button.addEventListener("click", () => {
        sendMessage(button.dataset.prompt || "");
    });
});

/*
|--------------------------------------------------------------------------
| Mobile sidebar
|--------------------------------------------------------------------------
*/

function openSidebar() {
    sidebar.classList.add("is-open");
    mobileOverlay.classList.add("is-visible");
}

function closeSidebar() {
    sidebar.classList.remove("is-open");
    mobileOverlay.classList.remove("is-visible");
}

document.getElementById("open-sidebar")
    .addEventListener("click", openSidebar);

document.getElementById("close-sidebar")
    .addEventListener("click", closeSidebar);

mobileOverlay.addEventListener("click", closeSidebar);

/*
|--------------------------------------------------------------------------
| New conversation
|--------------------------------------------------------------------------
*/

function startNewChat() {
    if (isSending) {
        return;
    }

    messages = [];

    clearAttachment();
    hideTyping();

    messagesElement.replaceChildren();
    welcomeScreen.hidden = false;

    messageInput.value = "";
    resizeTextarea();

    closeSidebar();
    messageInput.focus();
}

document.getElementById("new-chat")
    .addEventListener("click", startNewChat);

document.getElementById("header-new-chat")
    .addEventListener("click", startNewChat);

/*
|--------------------------------------------------------------------------
| Keyboard shortcuts
|--------------------------------------------------------------------------
*/

document.addEventListener("keydown", event => {
    if (
        (event.ctrlKey || event.metaKey) &&
        event.key.toLowerCase() === "k"
    ) {
        event.preventDefault();
        startNewChat();
    }

    if (event.key === "Escape") {
        closeSidebar();
    }
});

/*
|--------------------------------------------------------------------------
| Initialisation
|--------------------------------------------------------------------------
*/

loadGuestProfile();
renderAllMessages();
resizeTextarea();
checkHealth();
