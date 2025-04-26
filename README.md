Below is the complete content for your `README.md` file. You can copy this text into a file named `README.md` and save it in the root directory of your project. This file includes all the instructions you provided, formatted professionally in Markdown.

```markdown
# Inventory Management System (IMS)

Welcome to the Inventory Management System (IMS), a web-based application built with Flask and PostgreSQL to manage inventory, users, orders, and notifications. This README provides detailed instructions to set up and run the project on your local machine.

## Prerequisites

- **Operating System**: Windows (instructions tailored for Windows)
- **Software**:
  - [Python 3.8+](https://www.python.org/downloads/)
  - [PostgreSQL](https://www.postgresql.org/download/) with [pgAdmin](https://www.pgadmin.org/) for database management
  - [Visual Studio Code](https://code.visualstudio.com/) or any code editor
  - Git (optional, for cloning the repository)

## Project Structure

- `app.py`: Main Flask application file
- `database.py`: Database connection and utility functions
- `ims_sql.sql`: SQL script to set up the database schema and initial data
- `requirements.txt`: List of Python dependencies
- `templates/`: HTML templates for the web interface
- `venv/`: Virtual environment directory (created during setup)

## Setup Instructions

### 1. Export and Open the Project
- Export the project folder and save it to your desktop.
- Open the folder in Visual Studio Code or your preferred code editor.

### 2. Set Up Windows PowerShell
- Search for "Windows PowerShell" in the Start menu.
- Right-click and select "Run as administrator".
- Navigate to the project folder using the `cd` command. For example:
  ```powershell
  cd C:\Users\YourUsername\Desktop\Inventory_Management_System
  ```

### 3. Create a Virtual Environment
- Create a new virtual environment named `venv` by running:
  ```powershell
  python -m venv venv
  ```
- This creates an isolated Python environment for the project.

### 4. Activate the Virtual Environment
- Activate the virtual environment with:
  ```powershell
  venv\Scripts\activate
  ```
- You should see `(venv)` in your PowerShell prompt, indicating the environment is active.

### 5. Install Dependencies
- Install the required Python packages listed in `requirements.txt` by running:
  ```powershell
  pip install -r requirements.txt
  ```
- This will download and install Flask, psycopg2 (for PostgreSQL), and other dependencies.

### 6. Set Up the Database
- **Create a PostgreSQL Server**:
  - Open pgAdmin and create a new server named `ims`.
  - Set the password to `2802026` (or choose your own password—see note below).
- **Create a Database**:
  - In pgAdmin, create a new database named `inventory_management` under the `ims` server.
- **Run the SQL Script**:
  - Open the `ims_sql.sql` file in pgAdmin’s Query Tool.
  - Execute the script to set up the database schema, tables, procedures, triggers, and sample data.
- **Update Database Connection (if necessary)**:
  - Open `database.py` in your code editor.
  - If you used a custom password for the `ims` server, update the `get_db_connection` function to reflect your password. For example:
    ```python
    def get_db_connection():
        conn = psycopg2.connect(
            dbname="inventory_management",
            user="postgres",
            password="your_custom_password",  # Replace with your password
            host="localhost",
            port="5432"
        )
        return conn
    ```

### 7. Run the Application
- Open the project folder in Visual Studio Code.
- Open a new terminal in VS Code.
- Activate the virtual environment again (if not already active):
  ```powershell
  venv\Scripts\activate
  ```
- Run the Flask application:
  ```powershell
  python app.py
  ```
- You will see a message with a URL (e.g., `http://127.0.0.1:5000`). Open this URL in your web browser to access the IMS website.

## Usage
- Log in with the default admin credentials:
  - Username: `admin`
  - Password: `admin123`
- Explore features like adding products, managing orders, and viewing notifications.
- Register new users or manage inventory as per your role (Admin, InventoryManager, Sales, etc.).

## Troubleshooting
- **Database Connection Error**: Ensure the password in `database.py` matches your PostgreSQL server password.
- **Module Not Found**: Verify all dependencies are installed by re-running `pip install -r requirements.txt`.
- **Port Conflict**: If `http://127.0.0.1:5000` is in use, modify the port in `app.py` (e.g., `app.run(port=5001)`).
- **SQL Errors**: Check pgAdmin’s Query Tool output for errors when running `ims_sql.sql`.

## Contributing
Feel free to fork this repository, make improvements, and submit pull requests. Report issues or suggest features via the Issues tab.

## Contact
For support, contact yasinkhilji28@gmail.com .
