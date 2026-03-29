# Nutrition Analyzer Flask Application

A web-based AI-powered nutrition analysis application for fitness enthusiasts.

## Project Structure

```
Flask/
├── app/                    # Main application directory
│   ├── app.py             # Flask application main file
│   ├── nutrition.h5       # Trained ML model
│   ├── users.json         # User data storage
│   └── requirements.txt   # Python dependencies
├── static/                # Static assets
│   ├── css/
│   │   └── styles.css     # Application stylesheets
│   ├── images/            # Image assets
│   └── js/                # JavaScript files
├── templates/             # HTML templates
│   ├── home.html
│   ├── login.html
│   ├── register.html
│   ├── forgot_password.html
│   ├── profile.html
│   ├── image.html
│   ├── meal_plan.html
│   ├── share_meal.html
│   └── social.html
├── uploads/               # User uploaded images
├── Sample_Images/         # Sample images for testing
└── run.bat               # Windows batch file to run the app
```

## Features

- **User Registration/Login**: Secure user authentication with password confirmation
- **Forgot Password**: Password recovery functionality for existing users
- **Image Classification**: AI-powered fruit/vegetable recognition using TensorFlow
- **Nutrition Analysis**: Detailed nutritional information for identified foods
- **User Profiles**: Personalized health and fitness tracking
- **Meal Planning**: Generate customized meal plans
- **Social Features**: Share meals and connect with other users

## Improved Features

### Structured Forms
- Clean, responsive form layouts with proper spacing
- Consistent styling across all input fields
- Enhanced visual feedback and validation

### Example Email Checkbox
- Interactive checkbox on registration page
- Clicking shows example email: `user@example.com`
- Email field becomes read-only when checkbox is selected
- Easy way for users to test the registration functionality

## Installation & Setup

1. **Install Dependencies**:
   ```bash
   cd app
   pip install -r requirements.txt
   ```

2. **Run the Application**:
   - **Option 1**: Use the batch file (Windows)
     ```bash
     run.bat
     ```
   - **Option 2**: Manual execution
     ```bash
     # Activate virtual environment
     call ..\..\.venv\Scripts\activate.bat
     cd app
     python app.py
     ```

3. **Access the Application**:
   Open your browser and navigate to `http://localhost:5000`

## Usage

1. **Register**: Create a new account using the registration form
   - Use the "Use example email" checkbox for quick testing
   - Ensure passwords match in both fields

2. **Login**: Access your account with email and password
   - Use "Forgot Password?" link if you can't remember your password

3. **Forgot Password**: Reset your password by entering your email address
   - Enter your registered email to receive reset instructions

4. **Classify Images**: Upload fruit/vegetable images for AI analysis

5. **View Profile**: Update your health information and preferences

6. **Meal Planning**: Generate personalized nutrition plans

## Development

- **Frontend**: HTML5, CSS3, JavaScript
- **Backend**: Python Flask
- **AI/ML**: TensorFlow, Keras
- **Database**: JSON file storage (users.json)

## File Organization

The application has been restructured for better maintainability:
- Main application code moved to `app/` directory
- Clear separation of static assets, templates, and uploads
- Improved CSS organization with structured form styling
- Batch file for easy Windows deployment