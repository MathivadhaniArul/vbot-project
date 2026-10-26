const speak = (text: string) => {
  speechSynthesis.cancel();

  const utterance = new SpeechSynthesisUtterance(text);

  // Basic language detection
  if (/[\u0B80-\u0BFF]/.test(text)) {
    utterance.lang = "ta-IN";
  } else if (/[\u0900-\u097F]/.test(text)) {
    utterance.lang = "hi-IN";
  } else if (/[\u0C00-\u0C7F]/.test(text)) {
    utterance.lang = "te-IN";
  } else if (/[\u0C80-\u0CFF]/.test(text)) {
    utterance.lang = "kn-IN";
  } else if (/[\u0D00-\u0D7F]/.test(text)) {
    utterance.lang = "ml-IN";
  } else {
    utterance.lang = "en-US";
  }

  const voices = speechSynthesis.getVoices();

  const voice = voices.find((v) =>
    v.lang.startsWith(utterance.lang.split("-")[0])
  );

  if (voice) {
    utterance.voice = voice;
  }

  speechSynthesis.speak(utterance);
};