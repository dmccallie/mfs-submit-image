const setupDropzone = (root = document) => {
  const dropzone = root.querySelector('#dropzone');
  const fileInput = root.querySelector('#photo');
  const preview = root.querySelector('#preview');
  if (!dropzone || !fileInput || !preview) return;
  if (dropzone.dataset.initialized === 'true') return;
  dropzone.dataset.initialized = 'true';

  const showPreview = (file) => {
    if (!file) return;
    const url = URL.createObjectURL(file);
    preview.src = url;
    preview.style.display = 'block';
  };

  dropzone.addEventListener('dragover', (evt) => {
    evt.preventDefault();
    dropzone.classList.add('dragover');
  });

  dropzone.addEventListener('dragleave', () => {
    dropzone.classList.remove('dragover');
  });

  dropzone.addEventListener('drop', (evt) => {
    evt.preventDefault();
    dropzone.classList.remove('dragover');
    const [file] = evt.dataTransfer.files;
    if (file) {
      const dt = new DataTransfer();
      dt.items.add(file);
      fileInput.files = dt.files;
      showPreview(file);
    }
  });

  dropzone.addEventListener('click', () => {
    fileInput.click();
  });

  fileInput.addEventListener('change', (evt) => {
    const [file] = evt.target.files;
    showPreview(file);
  });
};

window.addEventListener('DOMContentLoaded', () => setupDropzone(document));
if (window.htmx) {
  htmx.onLoad((elt) => {
    setupDropzone(elt);
  });
  document.body.addEventListener('htmx:historyRestore', () => {
    setupDropzone(document);
  });
}
