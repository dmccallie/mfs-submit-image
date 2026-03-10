const setupDropzone = (root = document) => {
  const dropzone = root.querySelector('#dropzone');
  const fileInput = root.querySelector('#photo');
  const preview = root.querySelector('#preview');
  if (!dropzone || !fileInput || !preview) return;
  if (dropzone.dataset.initialized === 'true') return;
  dropzone.dataset.initialized = 'true';
  let metadataRequestId = 0;

  const showPreview = (file) => {
    if (!file) return;
    const url = URL.createObjectURL(file);
    preview.src = url;
    preview.style.display = 'block';
  };

  const applyMetadataToForm = (data) => {
    if (!data) return;

    const titleInput = root.querySelector('input[name="title"]');
    const descriptionInput = root.querySelector('textarea[name="description"]');
    const submittedByInput = root.querySelector('select[name="submitted_by"]');

    if (titleInput && data.title) {
      titleInput.value = data.title;
    }
    if (descriptionInput && data.description) {
      descriptionInput.value = data.description;
    }
    if (submittedByInput && data.submitted_by) {
      submittedByInput.value = data.submitted_by;
    }
  };

  const extractAndApplyMetadata = async (file) => {
    if (!file) return;
    metadataRequestId += 1;
    const requestId = metadataRequestId;
    const formData = new FormData();
    formData.append('photo', file, file.name || 'upload');

    try {
      const response = await fetch('/extract-metadata', {
        method: 'POST',
        body: formData,
      });
      if (!response.ok) return;
      const data = await response.json();

      // Ignore stale responses if a newer file was selected.
      if (requestId !== metadataRequestId) return;
      applyMetadataToForm(data);
    } catch (_err) {
      // Leave fields untouched if metadata extraction fails.
    }
  };

  const handleNewFile = (file) => {
    showPreview(file);
    extractAndApplyMetadata(file);
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
      handleNewFile(file);
    }
  });

  dropzone.addEventListener('click', () => {
    fileInput.click();
  });

  fileInput.addEventListener('change', (evt) => {
    const [file] = evt.target.files;
    handleNewFile(file);
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
