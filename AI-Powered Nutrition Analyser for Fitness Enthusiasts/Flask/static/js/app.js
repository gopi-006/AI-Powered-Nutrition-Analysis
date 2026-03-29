
const chooseButton = document.querySelector('button.primary-button');
const classifyButton = document.querySelector('button.secondary-button');

let userFile = null;


// ============================
// Choose Image
// ============================
chooseButton.addEventListener('click', function () {

    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/png, image/jpeg, image/jpg';
    input.name = 'file';

    input.click();

    input.onchange = function () {

        const imageViewer = document.querySelector('#image-viewer');

        const reader = new FileReader();

        reader.onload = function (event) {
            imageViewer.src = event.target.result;
            imageViewer.style.marginTop = '2rem';
            imageViewer.style.height = '300px';
            imageViewer.style.width = '300px';
        };

        reader.readAsDataURL(input.files[0]);

        userFile = input.files[0];
    };
});


// ============================
// Classify Image
// ============================
classifyButton.addEventListener('click', function () {

    if (!userFile) {
        alert("Please choose an image first.");
        return;
    }

    const formData = new FormData();
    formData.append('file', userFile);

    fetch('/predict', {
        method: 'POST',
        body: formData
    })
    .then(function (response) {
        return response.json();
    })
    .then(function (res) {

        const result = document.querySelector('#output-result');
        const apiResult = document.querySelector('#output-api-result');
        const outputWrapper = document.querySelector('#output-wrapper');
        const p = document.querySelector('#output > p');

        result.innerText = res.result;

        if (res.apiResult && res.apiResult.length > 0) {
            const nutrition = res.apiResult[0];
            let table = "<table border='1' cellpadding='8'>";
            table += "<tr><th>Nutrient</th><th>Value</th></tr>";
            table += "<tr><td>Calories</td><td>" + nutrition.calories + "</td></tr>";
            table += "<tr><td>Carbohydrates</td><td>" + nutrition.carbohydrates_total_g + " g</td></tr>";
            table += "<tr><td>Fat</td><td>" + nutrition.fat_total_g + " g</td></tr>";
            table += "<tr><td>Fiber</td><td>" + nutrition.fiber_g + " g</td></tr>";
            table += "<tr><td>Sugar</td><td>" + nutrition.sugar_g + " g</td></tr>";
            table += "<tr><td>Potassium</td><td>" + nutrition.potassium_mg + " mg</td></tr>";
            table += "<tr><td>Sodium</td><td>" + nutrition.sodium_mg + " mg</td></tr>";
            table += "</table>";
            apiResult.innerHTML = table;
        } else {
            apiResult.innerText = "No nutrition data available for this fruit or the classifier is unsure.";
        }

        const healthMessageEl = document.querySelector('#output-health-message');
        const bmiStatusEl = document.querySelector('#output-bmi-status');
        const foodRecoEl = document.querySelector('#output-food-reco');

        healthMessageEl.innerText = res.health_message ? `Health message: ${res.health_message}` : '';
        bmiStatusEl.innerText = res.bmi ? `BMI: ${res.bmi} (${res.is_pad === 'good' ? 'good' : 'needs improvement'})` : 'BMI: Not available. Please set your profile data.';
        foodRecoEl.innerText = res.food_recommendations && res.food_recommendations.length > 0 ? `Recommended foods: ${res.food_recommendations.join(', ')}` : '';

        p.style.display = "block";
        outputWrapper.style.display = "block";
    })
    .catch(function (error) {
        console.log(error);
        alert("Error fetching prediction result");
    });

});
