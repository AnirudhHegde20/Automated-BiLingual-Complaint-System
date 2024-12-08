import streamlit as st
from backend import fetch_backend_response
from utils import format_response
from dotenv import load_dotenv
import os
import webbrowser

# Load environment variables
load_dotenv()

# Get complaint constraints
COMPLAINT_MIN_LENGTH = int(os.getenv("COMPLAINT_MIN_LENGTH", 6))
COMPLAINT_MAX_LENGTH = int(os.getenv("COMPLAINT_MAX_LENGTH", 299))

# Function to reset input field
def reset_input():
    st.session_state["complaint_text"] = ""  # Clear the text field
    st.session_state["complaint_submitted"] = False  # Reset submission flag

def show_complaint_portal():
    st.title("📢 Customer Complaint Portal")
    st.write("We value your feedback and are committed to resolving your concerns promptly. Please describe your issue below.")

    # Add a "Back to Homepage" button below the title and center-align it
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("⬅️ Back to Homepage"):
            # Open the homepage in the browser
            webbrowser.open_new_tab("https://storage.cloud.google.com/frontend_homepage/homepage.html")
            return

    # Initialize session state
    if "complaint_text" not in st.session_state:
        st.session_state["complaint_text"] = ""
    if "complaint_submitted" not in st.session_state:
        st.session_state["complaint_submitted"] = False

    # Create a placeholder for the text area
    text_area_placeholder = st.empty()

    # If complaint is not yet submitted, show the text area
    if not st.session_state["complaint_submitted"]:
        with text_area_placeholder.container():
            # Multi-line input field
            st.text_area(
                "Describe your complaint:",
                value=st.session_state["complaint_text"],
                placeholder=f"Enter your complaint here... (min {9} and max {299} words)",
                height=150,
                key="complaint_text"
            )

    # Buttons in a row
    col1, col2 = st.columns([1, 1])
    with col1:
        # Submit button (enabled based on word count)
        submit_button = st.button("Submit")
    with col2:
        # Reset button to clear the text and state
        reset_button = st.button("Reset", on_click=reset_input)

    # Handle Submit button
    if submit_button:
        if st.session_state["complaint_text"].strip():
            try:
                response = fetch_backend_response(st.session_state["complaint_text"])
                if "error" in response and "validation" in response["error"]:
                    st.error("⚠️ Your complaint must be between 6 and 299 words. Please revise your complaint and try again.")
                elif "error" in response:
                    st.error(f"⚠️ {response['error']}")
                else:
                    formatted_response = format_response(
                        response.get("department", "other"),
                        response.get("product", "other"),
                    )
                    st.success("Your complaint has been registered successfully.")
                    st.markdown(formatted_response)

                    # Mark complaint as submitted to hide the text area
                    st.session_state["complaint_submitted"] = True
                    # Clear the placeholder for the text area after submission
                    text_area_placeholder.empty()
            except Exception as e:
                st.error(f"An error occurred: {str(e)}")
        else:
            st.error("⚠️ Complaint text cannot be empty.")

def main():
    # Directly show the complaint portal
    show_complaint_portal()

if __name__ == "__main__":
    main()
